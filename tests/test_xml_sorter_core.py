import os
import struct
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from xml_sorter_core import (
    QUICKTIME_EPOCH,
    analyze_xml,
    find_child,
    find_children,
    format_camera_offsets,
    get_best_creation_date,
    parse_camera_offsets,
    sort_sequences,
)


def write_media_file(directory, name, stamp):
    path = os.path.join(directory, name)
    with open(path, "wb") as handle:
        handle.write(b"test")
    timestamp = stamp.timestamp()
    os.utime(path, (timestamp, timestamp))
    return path


def write_quicktime_media_file(directory, name, recording_time, file_stamp):
    """Create a minimal MOV/MP4 file with a valid QuickTime ``mvhd`` atom."""
    path = os.path.join(directory, name)
    seconds = int((recording_time - QUICKTIME_EPOCH).total_seconds())
    mvhd_payload = b"\x00\x00\x00\x00" + struct.pack(">I", seconds) + b"\x00" * 12
    mvhd = struct.pack(">I4s", len(mvhd_payload) + 8, b"mvhd") + mvhd_payload
    moov = struct.pack(">I4s", len(mvhd) + 8, b"moov") + mvhd
    with open(path, "wb") as handle:
        handle.write(moov)
    timestamp = file_stamp.timestamp()
    os.utime(path, (timestamp, timestamp))
    return path


def file_url(path):
    return "file://" + path


class XMLSorterCoreTests(unittest.TestCase):
    def test_embedded_mov_mp4_dates_override_filesystem_dates_and_apply_camera_offset(self):
        with tempfile.TemporaryDirectory() as tempdir:
            s1_dir = os.path.join(tempdir, "00_S1II")
            iphone_dir = os.path.join(tempdir, "01_IPHONE")
            gopro_dir = os.path.join(tempdir, "04_GOPRO")
            for directory in (s1_dir, iphone_dir, gopro_dir):
                os.mkdir(directory)

            base = datetime(2024, 8, 1, 10, 0, tzinfo=timezone.utc)
            far_future = datetime(2030, 1, 1, 12, 0, 0)
            s1_path = write_quicktime_media_file(s1_dir, "P1000001.MOV", base, far_future)
            iphone_path = write_quicktime_media_file(
                iphone_dir, "IMG_0001.mov", base + timedelta(minutes=10), far_future
            )
            gopro_path = write_quicktime_media_file(
                gopro_dir, "GS010001.mp4", base + timedelta(minutes=20), far_future
            )

            xml_text = f"""<xmeml><sequence><media><video><track>
              <clipitem id="gopro"><start>0</start><end>10</end><file><pathurl>{file_url(gopro_path)}</pathurl></file></clipitem>
              <clipitem id="iphone"><start>10</start><end>20</end><file><pathurl>{file_url(iphone_path)}</pathurl></file></clipitem>
              <clipitem id="s1"><start>20</start><end>30</end><file><pathurl>{file_url(s1_path)}</pathurl></file></clipitem>
            </track></video></media></sequence></xmeml>"""

            root = ET.fromstring(xml_text)
            analysis = analyze_xml(root, tempdir, camera_offsets={"00_S1II": 3600})
            clips = analysis["sequences"][0]["video_tracks_data"]
            clips = [clip for track_clips in clips.values() for clip in track_clips]
            by_id = {clip["id"]: clip for clip in clips}

            expected_s1 = base.astimezone().replace(tzinfo=None) + timedelta(hours=1)
            self.assertEqual(by_id["s1"]["date"], expected_s1)
            self.assertEqual(by_id["s1"]["date_source"], "embedded")
            self.assertEqual(by_id["s1"]["camera_offset_rule"], "00_S1II")
            self.assertEqual(analysis["embedded_date_count"], 3)
            self.assertEqual(analysis["filesystem_date_count"], 0)
            self.assertEqual(analysis["offset_clip_count"], 1)

            sort_sequences(analysis["sequences"])
            track = analysis["sequences"][0]["sequence"].find("./media/video/track")
            self.assertEqual([clip.get("id") for clip in find_children(track, "clipitem")], ["iphone", "gopro", "s1"])

    def test_filesystem_date_is_used_when_embedded_date_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tempdir:
            expected = datetime(2024, 3, 2, 9, 30, 0)
            path = write_media_file(tempdir, "transcoded.mov", expected)
            self.assertEqual(get_best_creation_date(path), expected)

    def test_gopro_render_uses_matching_original_360_recording_time(self):
        with tempfile.TemporaryDirectory() as tempdir:
            original_time = datetime(2024, 8, 16, 4, 14, 36, tzinfo=timezone.utc)
            render_time = datetime(2024, 8, 16, 17, 53, 23, tzinfo=timezone.utc)
            far_future = datetime(2030, 1, 1, 12, 0, 0)
            write_quicktime_media_file(tempdir, "GS010592.360", original_time, far_future)
            rendered_path = write_quicktime_media_file(
                tempdir, "GS010592_2024-08-16_19-51-36-975.mp4", render_time, far_future
            )
            xml_text = f"""<xmeml><sequence><media><video><track>
              <clipitem id="render"><start>0</start><end>10</end><file><pathurl>{file_url(rendered_path)}</pathurl></file></clipitem>
            </track></video></media></sequence></xmeml>"""

            analysis = analyze_xml(ET.fromstring(xml_text), tempdir)
            clip = next(iter(analysis["sequences"][0]["video_tracks_data"].values()))[0]

            self.assertEqual(clip["date"], original_time.astimezone().replace(tzinfo=None))
            self.assertEqual(clip["date_source"], "gopro_original_360")
            self.assertEqual(analysis["gopro_original_360_date_count"], 1)
            self.assertEqual(analysis["embedded_date_count"], 0)

    def test_camera_offset_rules_are_validated_and_formatted(self):
        offsets = parse_camera_offsets("00_S1II = +01:00\n# comment\nGoPro = -00:30")
        self.assertEqual(offsets, {"00_S1II": 3600, "GoPro": -1800})
        self.assertEqual(format_camera_offsets(offsets), "00_S1II = +01:00\nGoPro = -00:30")
        with self.assertRaises(ValueError):
            parse_camera_offsets("S1II = 1 hour")

    def test_linked_audio_moves_with_linked_video_group(self):
        with tempfile.TemporaryDirectory() as tempdir:
            a_path = write_media_file(tempdir, "a.mov", datetime(2024, 1, 1, 10, 0, 0))
            b_path = write_media_file(tempdir, "b.mov", datetime(2024, 6, 1, 10, 0, 0))

            xml_text = f"""<?xml version="1.0" encoding="UTF-8"?>
<xmeml version="5">
  <sequence id="seq-1">
    <name>Seq 1</name>
    <media>
      <video>
        <track>
          <clipitem id="Bv">
            <name>B</name>
            <start>0</start>
            <end>90</end>
            <link>
              <mediatype>video</mediatype>
              <trackindex>1</trackindex>
              <clipindex>1</clipindex>
            </link>
            <link>
              <mediatype>audio</mediatype>
              <trackindex>1</trackindex>
              <clipindex>1</clipindex>
            </link>
            <file id="file-b">
              <pathurl>{file_url(b_path)}</pathurl>
            </file>
          </clipitem>
          <clipitem id="Av">
            <name>A</name>
            <start>100</start>
            <end>120</end>
            <link>
              <mediatype>video</mediatype>
              <trackindex>1</trackindex>
              <clipindex>2</clipindex>
            </link>
            <link>
              <mediatype>audio</mediatype>
              <trackindex>1</trackindex>
              <clipindex>2</clipindex>
            </link>
            <file id="file-a">
              <pathurl>{file_url(a_path)}</pathurl>
            </file>
          </clipitem>
        </track>
      </video>
      <audio>
        <track>
          <clipitem id="Ba">
            <name>B audio</name>
            <start>0</start>
            <end>90</end>
            <file id="file-b"/>
          </clipitem>
          <clipitem id="Aa">
            <name>A audio</name>
            <start>0</start>
            <end>120</end>
            <file id="file-a"/>
          </clipitem>
        </track>
      </audio>
    </media>
  </sequence>
</xmeml>
"""

            root = ET.fromstring(xml_text)
            analysis = analyze_xml(root, tempdir)
            sort_sequences(analysis["sequences"])

            sequence = analysis["sequences"][0]["sequence"]
            video_track = find_children(find_child(find_child(sequence, "media"), "video"), "track")[0]
            audio_track = find_children(find_child(find_child(sequence, "media"), "audio"), "track")[0]

            video_ids = [clip.get("id") for clip in find_children(video_track, "clipitem")]
            audio_ids = [clip.get("id") for clip in find_children(audio_track, "clipitem")]
            self.assertEqual(video_ids, ["Av", "Bv"])
            self.assertEqual(audio_ids, ["Aa", "Ba"])

            by_id = {
                clip.get("id"): clip
                for clip in sequence.iter()
                if clip.tag == "clipitem"
            }

            self.assertEqual(find_child(by_id["Aa"], "start").text, "0")
            self.assertEqual(find_child(by_id["Aa"], "end").text, "120")
            self.assertEqual(find_child(by_id["Ba"], "start").text, "120")
            self.assertEqual(find_child(by_id["Ba"], "end").text, "210")

            av_links = find_children(by_id["Av"], "link")
            bv_links = find_children(by_id["Bv"], "link")
            self.assertEqual(find_child(av_links[0], "clipindex").text, "1")
            self.assertEqual(find_child(av_links[1], "clipindex").text, "1")
            self.assertEqual(find_child(bv_links[0], "clipindex").text, "2")
            self.assertEqual(find_child(bv_links[1], "clipindex").text, "2")

    def test_unlinked_external_audio_moves_with_unique_video_match(self):
        with tempfile.TemporaryDirectory() as tempdir:
            a_path = write_media_file(tempdir, "a.mov", datetime(2024, 1, 1, 10, 0, 0))
            b_path = write_media_file(tempdir, "b.mov", datetime(2024, 6, 1, 10, 0, 0))

            xml_text = f"""<?xml version="1.0" encoding="UTF-8"?>
<xmeml version="5">
  <sequence id="seq-1">
    <name>Seq 1</name>
    <media>
      <video>
        <track>
          <clipitem id="Bv">
            <name>B</name>
            <start>0</start>
            <end>100</end>
            <file id="file-b">
              <pathurl>{file_url(b_path)}</pathurl>
            </file>
          </clipitem>
          <clipitem id="Av">
            <name>A</name>
            <start>120</start>
            <end>220</end>
            <file id="file-a">
              <pathurl>{file_url(a_path)}</pathurl>
            </file>
          </clipitem>
        </track>
      </video>
      <audio>
        <track>
          <clipitem id="MicB">
            <name>Mic B</name>
            <start>0</start>
            <end>100</end>
          </clipitem>
          <clipitem id="MicA">
            <name>Mic A</name>
            <start>120</start>
            <end>220</end>
          </clipitem>
        </track>
      </audio>
    </media>
  </sequence>
</xmeml>
"""

            root = ET.fromstring(xml_text)
            analysis = analyze_xml(root, tempdir)
            stats = sort_sequences(analysis["sequences"])

            self.assertEqual(stats["inferred_audio_clips"], 2)
            self.assertEqual(stats["unlinked_audio_clips"], 0)

            sequence = analysis["sequences"][0]["sequence"]
            by_id = {
                clip.get("id"): clip
                for clip in sequence.iter()
                if clip.tag == "clipitem"
            }

            self.assertEqual(find_child(by_id["Av"], "start").text, "0")
            self.assertEqual(find_child(by_id["Av"], "end").text, "100")
            self.assertEqual(find_child(by_id["MicA"], "start").text, "0")
            self.assertEqual(find_child(by_id["MicA"], "end").text, "100")
            self.assertEqual(find_child(by_id["Bv"], "start").text, "100")
            self.assertEqual(find_child(by_id["Bv"], "end").text, "200")
            self.assertEqual(find_child(by_id["MicB"], "start").text, "100")
            self.assertEqual(find_child(by_id["MicB"], "end").text, "200")

    def test_ambiguous_unlinked_audio_stays_in_place(self):
        with tempfile.TemporaryDirectory() as tempdir:
            a_path = write_media_file(tempdir, "a.mov", datetime(2024, 1, 1, 10, 0, 0))
            b_path = write_media_file(tempdir, "b.mov", datetime(2024, 6, 1, 10, 0, 0))

            xml_text = f"""<?xml version="1.0" encoding="UTF-8"?>
<xmeml version="5">
  <sequence id="seq-1">
    <name>Seq 1</name>
    <media>
      <video>
        <track>
          <clipitem id="Bv">
            <name>B</name>
            <start>0</start>
            <end>100</end>
            <file id="file-b">
              <pathurl>{file_url(b_path)}</pathurl>
            </file>
          </clipitem>
          <clipitem id="Av">
            <name>A</name>
            <start>100</start>
            <end>200</end>
            <file id="file-a">
              <pathurl>{file_url(a_path)}</pathurl>
            </file>
          </clipitem>
        </track>
      </video>
      <audio>
        <track>
          <clipitem id="MicX">
            <name>Mic X</name>
            <start>50</start>
            <end>150</end>
          </clipitem>
        </track>
      </audio>
    </media>
  </sequence>
</xmeml>
"""

            root = ET.fromstring(xml_text)
            analysis = analyze_xml(root, tempdir)
            stats = sort_sequences(analysis["sequences"])

            self.assertEqual(stats["inferred_audio_clips"], 0)
            self.assertEqual(stats["unlinked_audio_clips"], 1)

            sequence = analysis["sequences"][0]["sequence"]
            mic = next(clip for clip in sequence.iter() if clip.get("id") == "MicX")
            self.assertEqual(find_child(mic, "start").text, "50")
            self.assertEqual(find_child(mic, "end").text, "150")

    def test_sequences_are_sorted_independently(self):
        with tempfile.TemporaryDirectory() as tempdir:
            seq1_path = write_media_file(tempdir, "seq1.mov", datetime(2024, 6, 1, 10, 0, 0))
            seq2_path = write_media_file(tempdir, "seq2.mov", datetime(2024, 1, 1, 10, 0, 0))

            xml_text = f"""<?xml version="1.0" encoding="UTF-8"?>
<xmeml version="5">
  <sequence id="seq-1">
    <name>Seq 1</name>
    <media>
      <video>
        <track>
          <clipitem id="S1">
            <name>S1</name>
            <start>0</start>
            <end>50</end>
            <file id="file-s1">
              <pathurl>{file_url(seq1_path)}</pathurl>
            </file>
          </clipitem>
        </track>
      </video>
    </media>
  </sequence>
  <sequence id="seq-2">
    <name>Seq 2</name>
    <media>
      <video>
        <track>
          <clipitem id="S2">
            <name>S2</name>
            <start>0</start>
            <end>60</end>
            <file id="file-s2">
              <pathurl>{file_url(seq2_path)}</pathurl>
            </file>
          </clipitem>
        </track>
      </video>
    </media>
  </sequence>
</xmeml>
"""

            root = ET.fromstring(xml_text)
            analysis = analyze_xml(root, tempdir)
            sort_sequences(analysis["sequences"])

            first_sequence = analysis["sequences"][0]["sequence"]
            second_sequence = analysis["sequences"][1]["sequence"]

            first_clip = find_children(
                find_children(find_child(find_child(first_sequence, "media"), "video"), "track")[0],
                "clipitem",
            )[0]
            second_clip = find_children(
                find_children(find_child(find_child(second_sequence, "media"), "video"), "track")[0],
                "clipitem",
            )[0]

            self.assertEqual(find_child(first_clip, "start").text, "0")
            self.assertEqual(find_child(first_clip, "end").text, "50")
            self.assertEqual(find_child(second_clip, "start").text, "0")
            self.assertEqual(find_child(second_clip, "end").text, "60")


if __name__ == "__main__":
    unittest.main()
