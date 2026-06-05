import os
import platform
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime


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


def build_clip_data(clip, track, track_type, track_index, clip_index, base_dir, mapping, file_id_to_path):
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

    return {
        "element": clip,
        "track": track,
        "track_type": track_type,
        "track_index": track_index,
        "clip_index": clip_index,
        "orig_clip_index": clip_index,
        "id": clip.get("id", "?"),
        "path": existing,
        "date": get_file_creation_date(existing) if existing and track_type == "video" else None,
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


def analyze_xml(root, base_dir, mapping=None):
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
                    clip, track, "video", track_index, clip_index, base_dir, mapping, file_id_to_path
                )
                if clip_data["date"]:
                    sequence_found += 1
                    sequence_dates.append(clip_data["date"])
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
                    clip, track, "audio", track_index, clip_index, base_dir, mapping, file_id_to_path
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
