#!/usr/bin/env python3
"""Publish the reviewed English translation of note's writing guidance."""
import argparse
import hashlib
from pathlib import Path

# Refresh this digest only after reviewing the translation against changed rules.
TRANSLATED_SOURCE_SHA256 = "05eac36c45ddb384214b01255b10f3edee315c4d719dd22a031223707422b878"

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repo', type=Path, required=True)
args = parser.parse_args()
base = Path(__file__).resolve().parents[1]
text = (base / 'SKILL.md').read_text(encoding='utf-8')
section = text.split('## 讲述式技术笔记\n', 1)[1].split('\n## ', 1)[0].strip()
if hashlib.sha256(section.encode('utf-8')).hexdigest() != TRANSLATED_SOURCE_SHA256:
    parser.error('Writing rules changed. Review assets/oceanct-humanize-SKILL.md, then update TRANSLATED_SOURCE_SHA256.')
portable = (base / 'assets/oceanct-humanize-SKILL.md').read_text(encoding='utf-8')
if not portable.isascii():
    parser.error('The public attachment must remain ASCII-compatible English.')
asset = args.repo / 'source/downloads/oceanct-humanize-SKILL.txt'
asset.parent.mkdir(parents=True, exist_ok=True)
asset.write_text(portable, encoding='utf-8')
print('Generated English Humanize attachment:', asset)
