import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime

from xml_sorter_core import analyze_xml, find_child, find_children, sort_sequences


def write_media_file(directory, name, stamp):
    path = os.path.join(directory, name)
    with open(path, "wb") as handle:
        handle.write(b"test")
    timestamp = stamp.timestamp()
    os.utime(path, (timestamp, timestamp))
    return path


def file_url(path):
    return "file://" + path


class XMLSorterCoreTests(unittest.TestCase):
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
