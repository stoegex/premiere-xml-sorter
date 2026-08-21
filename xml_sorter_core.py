import os
import platform
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import re
from io import StringIO
import struct


QUICKTIME_EPOCH = datetime(1904, 1, 1, tzinfo=timezone.utc)
MEDIA_EXTENSIONS = {".mov", ".mp4", ".m4v", ".360"}
GOPRO_RENDER_PATTERN = re.compile(r"^(GS\d{6})_.+\.mp4$", re.IGNORECASE)

def parse_with_repair(filepath, logger=None):
    try:
        return ET.parse(filepath), False
    except ET.ParseError as e:
        if logger:
            logger(f"[Warnung] XML ParseError: {e}. Versuche automatische Reparatur...")

        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()

        if content.rfind('<') > content.rfind('>'):
            content += '>'

        stack = []
        tag_pattern = re.compile(r'<(/?)(\w+)([^>]*)>')
        for match in tag_pattern.finditer(content):
            is_closing = match.group(1) == '/'
            tag_name = match.group(2)
            attrs = match.group(3)
            is_self_closing = attrs.strip().endswith('/')
            if is_self_closing or tag_name.lower() == 'xml' or tag_name.lower().startswith('?'):
                continue
            if not is_closing:
                stack.append(tag_name)
            else:
                if stack and stack[-1] == tag_name:
                    stack.pop()
                elif tag_name in stack:
                    while stack and stack.pop() != tag_name:
                        pass
        for tag in reversed(stack):
            content += f'</{tag}>'
        try:
            return ET.parse(StringIO(content)), True
        except Exception as e2:
            raise Exception(f"XML konnte auch nach Reparaturversuch nicht gelesen werden: {e2}")


def local_name(tag):
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def qualified_tag(parent, name):
    if parent.tag.startswith("{"):
        return parent.tag.split("}", 1)[0] + "}" + name
    return name


def find_child(element, name):
    for child in element:
        if local_name(child.tag) == name:
            return child
    return None


def find_children(element, name):
    return [child for child in element if local_name(child.tag) == name]


def get_int_child(element, name, default=0):
    child = find_child(element, name)
    if child is None or not child.text:
        return default
    try:
        return int(child.text)
    except ValueError:
        return default


def set_int_child(element, name, value):
    child = find_child(element, name)
    if child is not None:
        child.text = str(value)


def append_text_child(parent, name, text):
    child = ET.Element(qualified_tag(parent, name))
    child.text = str(text)
    parent.append(child)
    return child



def _iter_iso_boxes(handle, end_position):
    """Yield ISO-BMFF boxes without loading potentially large media files."""
    while handle.tell() + 8 <= end_position:
        start = handle.tell()
        header = handle.read(8)
        size, box_type = struct.unpack(">I4s", header)
        header_size = 8

        if size == 1:
            extended_size = handle.read(8)
            if len(extended_size) != 8:
                return
            size = struct.unpack(">Q", extended_size)[0]
            header_size = 16
        elif size == 0:
            size = end_position - start

        if size < header_size or start + size > end_position:
            return

        yield box_type, start, size, header_size
        handle.seek(start + size)


def get_embedded_creation_date(filepath):
    """Read the QuickTime/MP4 movie-header creation time, if available.

    MOV and MP4 from common cameras store an ISO-BMFF ``mvhd`` atom.  Reading
    that atom is deliberately dependency-free and does not require decoding the
    file.  Its timestamp is UTC, so it is converted to the local wall-clock
    time used for filesystem timestamps before sorting.
    """
    if not filepath or not os.path.exists(filepath):
        return None
    if os.path.splitext(filepath)[1].lower() not in MEDIA_EXTENSIONS:
        return None

    try:
        file_size = os.path.getsize(filepath)
        with open(filepath, "rb") as handle:
            for box_type, start, size, header_size in _iter_iso_boxes(handle, file_size):
                if box_type != b"moov":
                    continue

                moov_end = start + size
                handle.seek(start + header_size)
                for child_type, child_start, child_size, child_header_size in _iter_iso_boxes(handle, moov_end):
                    if child_type != b"mvhd":
                        continue

                    handle.seek(child_start + child_header_size)
                    version_data = handle.read(4)
                    if len(version_data) != 4:
                        return None
                    version = version_data[0]
                    timestamp_size = 8 if version == 1 else 4
                    raw_timestamp = handle.read(timestamp_size)
                    if len(raw_timestamp) != timestamp_size:
                        return None
                    seconds = struct.unpack(">Q" if version == 1 else ">I", raw_timestamp)[0]
                    if seconds == 0:
                        return None

                    value = QUICKTIME_EPOCH + timedelta(seconds=seconds)
                    # Zero or wildly future values are common placeholders in
                    # transcodes and should not outrank a usable file timestamp.
                    if value.year < 1970 or value > datetime.now(timezone.utc) + timedelta(days=366):
                        return None
                    return value.astimezone().replace(tzinfo=None)
    except (OSError, OverflowError, struct.error, ValueError):
        return None

    return None


def find_gopro_original_360(rendered_path):
    """Return the original GoPro 360 file for a rendered MP4, when unambiguous.

    GoPro Player exports use names such as ``GS010592_2026-08-16_19-51-36.mp4``
    while the camera original is ``GS010592.360`` in the same directory.
    Restricting the match to this exact prefix avoids accidentally pairing an
    arbitrary MP4 with a neighbouring 360 file.
    """
    if not rendered_path or os.path.splitext(rendered_path)[1].lower() != ".mp4":
        return None

    match = GOPRO_RENDER_PATTERN.match(os.path.basename(rendered_path))
    if not match:
        return None

    directory = os.path.dirname(rendered_path)
    original_stem = match.group(1)
    candidate = os.path.join(directory, f"{original_stem}.360")
    if os.path.exists(candidate):
        return candidate

    # Case-sensitive filesystems need a small directory lookup for uppercase
    # or lowercase filename variants.  This is limited to the render's folder.
    try:
        expected_name = f"{original_stem}.360".lower()
        for filename in os.listdir(directory):
            if filename.lower() == expected_name:
                candidate = os.path.join(directory, filename)
                if os.path.isfile(candidate):
                    return candidate
    except OSError:
        pass
    return None


def parse_camera_offsets(text):
    """Parse one ``path fragment = +/-HH:MM`` rule per line."""
    offsets = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Zeile {line_number}: Erwartet wird 'Pfadteil = +HH:MM'.")

        path_fragment, raw_offset = (part.strip() for part in line.split("=", 1))
        match = re.fullmatch(r"([+-])(\d{1,2}):(\d{2})", raw_offset)
        if not path_fragment or not match:
            raise ValueError(f"Zeile {line_number}: Ungültige Zeitkorrektur '{line}'.")

        hours, minutes = int(match.group(2)), int(match.group(3))
        if minutes >= 60 or hours > 23:
            raise ValueError(f"Zeile {line_number}: Ungültige Zeitkorrektur '{raw_offset}'.")
        seconds = hours * 3600 + minutes * 60
        offsets[path_fragment] = seconds if match.group(1) == "+" else -seconds
    return offsets


def format_camera_offsets(offsets):
    lines = []
    for path_fragment, seconds in sorted(offsets.items(), key=lambda item: item[0].lower()):
        sign = "+" if seconds >= 0 else "-"
        minutes = abs(seconds) // 60
        lines.append(f"{path_fragment} = {sign}{minutes // 60:02d}:{minutes % 60:02d}")
    return "\n".join(lines)


def get_camera_offset(filepath, camera_offsets):
    if not filepath or not camera_offsets:
        return 0, None

    normalized_path = os.path.normcase(os.path.normpath(filepath)).replace("\\", "/")
    matches = [
        (len(fragment), fragment, seconds)
        for fragment, seconds in camera_offsets.items()
        if fragment and fragment.replace("\\", "/").lower() in normalized_path.lower()
    ]
    if not matches:
        return 0, None

    _, fragment, seconds = max(matches, key=lambda item: item[0])
    return seconds, fragment


def get_sort_date(filepath, camera_offsets=None):
    """Return a sortable date plus its source and matching offset rule."""
    original_360 = find_gopro_original_360(filepath)
    original_360_date = get_embedded_creation_date(original_360) if original_360 else None
    embedded = get_embedded_creation_date(filepath)

    if original_360_date is not None:
        date = original_360_date
        source = "gopro_original_360"
    elif embedded is not None:
        date = embedded
        source = "embedded"
    else:
        date = get_file_creation_date(filepath)
        source = "filesystem" if date else None

    offset, offset_rule = get_camera_offset(filepath, camera_offsets)
    if date is not None and offset:
        date += timedelta(seconds=offset)
    return date, source, offset_rule


def get_best_creation_date(filepath, camera_offsets=None):
    """Prefer embedded recording metadata; fall back only to this file's date."""
    return get_sort_date(filepath, camera_offsets)[0]



def get_file_creation_date(filepath):
    if not filepath or not os.path.exists(filepath):
        return None
    try:
        stat = os.stat(filepath)
        if hasattr(stat, "st_birthtime"):
            birth = datetime.fromtimestamp(stat.st_birthtime)
            mtime = datetime.fromtimestamp(stat.st_mtime)
            return min(birth, mtime)
        return datetime.fromtimestamp(stat.st_mtime)
    except Exception:
        return None


def resolve_path(url_str, base_dir, mapping=None):
    if not url_str:
        return None
    url_str = urllib.parse.unquote(url_str.strip())
    if url_str.startswith("file://"):
        parsed = urllib.parse.urlparse(url_str)
        path = parsed.path
        if platform.system() == "Windows" and path.startswith("/"):
            path = path[1:]
        if not path and parsed.netloc:
            path = parsed.netloc
    else:
        path = url_str

    if mapping:
        for old, new in mapping.items():
            if path.startswith(old):
                path = new + path[len(old):]
                break

    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(base_dir, path))


def find_all_file_paths(clipitem, base_dir, mapping=None):
    found = []
    added = set()

    def add(resolved, source):
        if resolved and resolved not in added:
            added.add(resolved)
            found.append((resolved, source))

    for file_elem in clipitem.findall(".//{*}file"):
        for pathurl in file_elem.findall("{*}pathurl"):
            if pathurl.text:
                add(resolve_path(pathurl.text.strip(), base_dir, mapping), "file/pathurl")
        for name in file_elem.findall("{*}name"):
            if name.text:
                add(resolve_path(name.text.strip(), base_dir, mapping), "file/name")
        for url in file_elem.findall("{*}url"):
            if url.text:
                add(resolve_path(url.text.strip(), base_dir, mapping), "file/url")

    for link in find_children(clipitem, "link"):
        for file_elem in link.findall(".//{*}file"):
            for pathurl in file_elem.findall("{*}pathurl"):
                if pathurl.text:
                    add(resolve_path(pathurl.text.strip(), base_dir, mapping), "link/…")

    return found


def indent(elem, level=0):
    indent_str = "  "
    spacer = "\n" + level * indent_str
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = spacer + indent_str
        for child in elem:
            indent(child, level + 1)
            if not child.tail or not child.tail.strip():
                child.tail = spacer + indent_str
        if not elem.tail or not elem.tail.strip():
            elem.tail = spacer
    elif level and (not elem.tail or not elem.tail.strip()):
        elem.tail = spacer


def build_file_registry(root, base_dir, mapping=None):
    file_id_to_path = {}
    for file_elem in root.iter():
        if local_name(file_elem.tag) != "file":
            continue
        file_id = file_elem.get("id")
        if not file_id:
            continue
        for pathurl in file_elem.findall("{*}pathurl"):
            if pathurl.text:
                resolved = resolve_path(pathurl.text.strip(), base_dir, mapping)
                if resolved:
                    file_id_to_path[file_id] = resolved
                    break
    return file_id_to_path


def build_clip_data(
    clip,
    track,
    track_type,
    track_index,
    clip_index,
    base_dir,
    mapping,
    file_id_to_path,
    camera_offsets=None,
):
    paths = find_all_file_paths(clip, base_dir, mapping)
    existing = next((path for path, _ in paths if os.path.exists(path)), None)

    if not existing:
        for file_elem in clip.findall(".//{*}file"):
            file_id = file_elem.get("id")
            if file_id and file_id in file_id_to_path:
                candidate = file_id_to_path[file_id]
                if os.path.exists(candidate):
                    existing = candidate
                    break

    macos_paths = {
        path for path, _ in paths
        if path and (path.startswith("/Volumes/") or path.startswith("/Users/"))
    }

    date, date_source, offset_rule = get_sort_date(existing, camera_offsets) \
        if existing and track_type == "video" else (None, None, None)

    return {
        "element": clip,
        "track": track,
        "track_type": track_type,
        "track_index": track_index,
        "clip_index": clip_index,
        "orig_clip_index": clip_index,
        "id": clip.get("id", "?"),
        "path": existing,
        "date": date,
        "date_source": date_source,
        "camera_offset_rule": offset_rule,
        "orig_start": get_int_child(clip, "start"),
        "orig_end": get_int_child(clip, "end"),
        "new_start": get_int_child(clip, "start"),
        "new_end": get_int_child(clip, "end"),
        "paths": paths,
        "macos_paths": macos_paths,
        "links": parse_links(clip),
        "groupindex": None,
        "group_id": None,
    }


def parse_links(clip):
    links = []
    for link in find_children(clip, "link"):
        entry = {
            "linkclipref": None,
            "mediatype": None,
            "trackindex": None,
            "clipindex": None,
            "groupindex": None,
        }
        linkclipref = find_child(link, "linkclipref")
        if linkclipref is not None and linkclipref.text:
            entry["linkclipref"] = linkclipref.text.strip()
        mediatype = find_child(link, "mediatype")
        if mediatype is not None and mediatype.text:
            entry["mediatype"] = mediatype.text.strip().lower()
        trackindex = find_child(link, "trackindex")
        if trackindex is not None and trackindex.text:
            try:
                entry["trackindex"] = int(trackindex.text)
            except ValueError:
                entry["trackindex"] = None
        clipindex = find_child(link, "clipindex")
        if clipindex is not None and clipindex.text:
            try:
                entry["clipindex"] = int(clipindex.text)
            except ValueError:
                entry["clipindex"] = None
        groupindex = find_child(link, "groupindex")
        if groupindex is not None and groupindex.text:
            try:
                entry["groupindex"] = int(groupindex.text)
            except ValueError:
                entry["groupindex"] = None
        links.append(entry)
    return links


def analyze_xml(root, base_dir, mapping=None, camera_offsets=None):
    file_id_to_path = build_file_registry(root, base_dir, mapping)
    sequences = [elem for elem in root.iter() if local_name(elem.tag) == "sequence"]
    contexts = []
    all_dates = []
    macos_paths = set()
    warnings = []
    total_found = 0
    total_missing = 0
    video_clip_count = 0
    audio_clip_count = 0
    embedded_date_count = 0
    filesystem_date_count = 0
    gopro_original_360_date_count = 0
    offset_clip_count = 0

    for sequence in sequences:
        media = find_child(sequence, "media")
        if media is None:
            continue

        video_elem = find_child(media, "video")
        audio_elem = find_child(media, "audio")
        video_tracks = find_children(video_elem, "track") if video_elem is not None else []
        audio_tracks = find_children(audio_elem, "track") if audio_elem is not None else []
        if not video_tracks and not audio_tracks:
            continue

        video_tracks_data = {}
        audio_tracks_data = {}
        sequence_clips = []
        sequence_dates = []
        sequence_macos_paths = set()
        sequence_found = 0
        sequence_missing = 0

        for track_index, track in enumerate(video_tracks, start=1):
            track_clips = []
            for clip_index, clip in enumerate(find_children(track, "clipitem"), start=1):
                clip_data = build_clip_data(
                    clip,
                    track,
                    "video",
                    track_index,
                    clip_index,
                    base_dir,
                    mapping,
                    file_id_to_path,
                    camera_offsets,
                )
                if clip_data["date"]:
                    sequence_found += 1
                    sequence_dates.append(clip_data["date"])
                    if clip_data["date_source"] == "gopro_original_360":
                        gopro_original_360_date_count += 1
                    elif clip_data["date_source"] == "embedded":
                        embedded_date_count += 1
                    elif clip_data["date_source"] == "filesystem":
                        filesystem_date_count += 1
                    if clip_data["camera_offset_rule"]:
                        offset_clip_count += 1
                else:
                    sequence_missing += 1
                sequence_macos_paths.update(clip_data["macos_paths"])
                track_clips.append(clip_data)
                sequence_clips.append(clip_data)
            if track_clips:
                video_tracks_data[track] = track_clips

        for track_index, track in enumerate(audio_tracks, start=1):
            track_clips = []
            for clip_index, clip in enumerate(find_children(track, "clipitem"), start=1):
                clip_data = build_clip_data(
                    clip,
                    track,
                    "audio",
                    track_index,
                    clip_index,
                    base_dir,
                    mapping,
                    file_id_to_path,
                    camera_offsets,
                )
                sequence_macos_paths.update(clip_data["macos_paths"])
                track_clips.append(clip_data)
                sequence_clips.append(clip_data)
            if track_clips:
                audio_tracks_data[track] = track_clips

        groups, link_warnings = build_link_groups(sequence_clips)
        warnings.extend(link_warnings)

        contexts.append({
            "sequence": sequence,
            "video_tracks_data": video_tracks_data,
            "audio_tracks_data": audio_tracks_data,
            "all_clips": sequence_clips,
            "groups": groups,
            "all_dates": sequence_dates,
            "macos_paths": sequence_macos_paths,
            "total_found": sequence_found,
            "total_missing": sequence_missing,
            "video_clip_count": sum(len(clips) for clips in video_tracks_data.values()),
            "audio_clip_count": sum(len(clips) for clips in audio_tracks_data.values()),
        })

        all_dates.extend(sequence_dates)
        macos_paths.update(sequence_macos_paths)
        total_found += sequence_found
        total_missing += sequence_missing
        video_clip_count += contexts[-1]["video_clip_count"]
        audio_clip_count += contexts[-1]["audio_clip_count"]

    return {
        "sequences": contexts,
        "file_registry_count": len(file_id_to_path),
        "all_dates": all_dates,
        "macos_paths": macos_paths,
        "warnings": warnings,
        "total_found": total_found,
        "total_missing": total_missing,
        "video_clip_count": video_clip_count,
        "audio_clip_count": audio_clip_count,
        "embedded_date_count": embedded_date_count,
        "filesystem_date_count": filesystem_date_count,
        "gopro_original_360_date_count": gopro_original_360_date_count,
        "offset_clip_count": offset_clip_count,
    }


def build_link_groups(clips):
    parent = {index: index for index in range(len(clips))}
    by_key = {}
    by_id = {}
    warnings = []

    for index, clip in enumerate(clips):
        clip["uid"] = index
        by_key[(clip["track_type"], clip["track_index"], clip["clip_index"])] = clip
        clip_id = clip.get("id")
        if clip_id and clip_id != "?":
            by_id.setdefault(clip_id, []).append(clip)

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left, right):
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for clip in clips:
        for link in clip["links"]:
            target = None
            if link["linkclipref"]:
                matches = by_id.get(link["linkclipref"], [])
                if len(matches) == 1:
                    target = matches[0]
                elif len(matches) > 1:
                    warnings.append(
                        f"Mehrdeutiges linkclipref '{link['linkclipref']}' in Clip {clip['id']}"
                    )
            else:
                key = (link["mediatype"], link["trackindex"], link["clipindex"])
                if all(part is not None for part in key):
                    target = by_key.get(key)

            if target is None:
                continue

            if link["groupindex"] is not None and target["track_type"] == "audio":
                target["groupindex"] = link["groupindex"]
            union(clip["uid"], target["uid"])

    grouped = {}
    for clip in clips:
        group_root = find(clip["uid"])
        grouped.setdefault(group_root, []).append(clip)

    groups = []
    for group_id, members in grouped.items():
        for member in members:
            member["group_id"] = group_id
        groups.append({
            "id": group_id,
            "members": members,
            "movable": any(member["track_type"] == "video" for member in members),
        })

    return groups, warnings


def sort_sequences(sequence_contexts):
    total_groups = 0
    moved_groups = 0
    unlinked_audio = 0
    inferred_audio = 0

    for context in sequence_contexts:
        groups = context["groups"]
        total_groups += len(groups)

        movable_groups = []
        for group in groups:
            members = group["members"]
            group["min_start"] = min(member["orig_start"] for member in members)
            group["max_end"] = max(member["orig_end"] for member in members)
            group["duration"] = group["max_end"] - group["min_start"]

            video_members = [member for member in members if member["track_type"] == "video"]
            dated_members = [member["date"] for member in video_members if member["date"] is not None]
            group["sort_date"] = min(dated_members) if dated_members else None
            group["tie_breaker"] = min(
                (member["orig_start"], member["track_index"], member["orig_clip_index"])
                for member in video_members
            ) if video_members else (float("inf"), float("inf"), float("inf"))

            if group["movable"]:
                movable_groups.append(group)

        inferred_audio += infer_audio_group_anchors(groups)

        sorted_groups = sorted(
            movable_groups,
            key=lambda group: (
                group["sort_date"] is None,
                group["sort_date"] if group["sort_date"] is not None else datetime.max,
                group["tie_breaker"],
            ),
        )

        for clip in context["all_clips"]:
            clip["new_start"] = clip["orig_start"]
            clip["new_end"] = clip["orig_end"]

        current_pos = 0
        for group in sorted_groups:
            offset = current_pos - group["min_start"]
            if offset != 0:
                moved_groups += 1
            for member in group["members"]:
                member["new_start"] = member["orig_start"] + offset
                member["new_end"] = member["orig_end"] + offset
                set_int_child(member["element"], "start", member["new_start"])
                set_int_child(member["element"], "end", member["new_end"])

            for attached_group in group.get("attached_audio_groups", []):
                for member in attached_group["members"]:
                    member["new_start"] = member["orig_start"] + offset
                    member["new_end"] = member["orig_end"] + offset
                    set_int_child(member["element"], "start", member["new_start"])
                    set_int_child(member["element"], "end", member["new_end"])
            current_pos += group["duration"]

        for group in groups:
            if not group["movable"] and group.get("anchor_group") is None:
                unlinked_audio += len(group["members"])

        for track_map in (context["video_tracks_data"], context["audio_tracks_data"]):
            for track, clips in list(track_map.items()):
                sorted_clips = sorted(
                    clips,
                    key=lambda clip: (clip["new_start"], clip["track_index"], clip["orig_clip_index"]),
                )
                track_map[track] = sorted_clips
                reorder_track(track, sorted_clips)
                for clip_index, clip in enumerate(sorted_clips, start=1):
                    clip["clip_index"] = clip_index

        rebuild_links(context["groups"])

    return {
        "sequence_count": len(sequence_contexts),
        "group_count": total_groups,
        "moved_groups": moved_groups,
        "unlinked_audio_clips": unlinked_audio,
        "inferred_audio_clips": inferred_audio,
    }


def reorder_track(track, sorted_clips):
    children = list(track)
    clip_indices = [
        index for index, child in enumerate(children)
        if local_name(child.tag) == "clipitem"
    ]
    for index, clip in zip(clip_indices, sorted_clips):
        children[index] = clip["element"]
    track[:] = children


def rebuild_links(groups):
    for group in groups:
        for member in group["members"]:
            remove_direct_children(member["element"], "link")

        if len(group["members"]) < 2:
            continue

        ordered_members = sorted(
            group["members"],
            key=lambda member: (
                member["track_type"] != "video",
                member["track_index"],
                member["clip_index"],
            ),
        )

        for member in group["members"]:
            for target in ordered_members:
                append_link(member["element"], target)


def remove_direct_children(element, name):
    for child in list(element):
        if local_name(child.tag) == name:
            element.remove(child)


def append_link(clip, target):
    link = ET.Element(qualified_tag(clip, "link"))
    append_text_child(link, "mediatype", target["track_type"])
    append_text_child(link, "trackindex", target["track_index"])
    append_text_child(link, "clipindex", target["clip_index"])
    if target["track_type"] == "audio" and target["groupindex"] is not None:
        append_text_child(link, "groupindex", target["groupindex"])
    clip.append(link)


def infer_audio_group_anchors(groups):
    inferred_members = 0
    video_groups = [group for group in groups if group["movable"]]
    audio_groups = [group for group in groups if not group["movable"]]

    for group in groups:
        group["anchor_group"] = None
        group["attached_audio_groups"] = []

    for audio_group in audio_groups:
        target_group = find_best_anchor_group(audio_group, video_groups)
        if target_group is None:
            continue
        audio_group["anchor_group"] = target_group
        target_group.setdefault("attached_audio_groups", []).append(audio_group)
        inferred_members += len(audio_group["members"])

    return inferred_members


def find_best_anchor_group(audio_group, video_groups):
    candidates = []
    audio_start = audio_group["min_start"]
    audio_end = audio_group["max_end"]
    audio_duration = max(1, audio_end - audio_start)

    for video_group in video_groups:
        video_start = video_group["min_start"]
        video_end = video_group["max_end"]
        overlap = min(audio_end, video_end) - max(audio_start, video_start)
        if overlap <= 0:
            continue

        overlap_ratio = overlap / audio_duration
        start_delta = abs(audio_start - video_start)
        end_delta = abs(audio_end - video_end)
        contains_audio = video_start <= audio_start and video_end >= audio_end
        exact_match = start_delta == 0 and end_delta == 0
        exact_start = start_delta == 0

        score = (
            1 if exact_match else 0,
            1 if exact_start else 0,
            1 if contains_audio else 0,
            round(overlap_ratio, 6),
            -start_delta,
            -end_delta,
            -abs(video_group["duration"] - audio_duration),
        )
        candidates.append((score, video_group))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    best_score, best_group = candidates[0]

    strong_match = (
        best_score[0] == 1
        or best_score[1] == 1
        or best_score[2] == 1
        or best_score[3] >= 0.9
    )
    if not strong_match:
        return None

    if len(candidates) > 1:
        second_score = candidates[1][0]
        if second_score == best_score:
            return None
        if best_score[0:4] == second_score[0:4] and abs(best_score[4] - second_score[4]) <= 2:
            return None

    return best_group
