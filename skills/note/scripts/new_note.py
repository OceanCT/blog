#!/usr/bin/env python3
"""Create a Hexo post without overwriting an existing note."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--slug', required=True)
    parser.add_argument('--title', required=True)
    parser.add_argument('--description', required=True)
    parser.add_argument('--tags', nargs='*', default=[])
    parser.add_argument('--body-file', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', args.slug):
        parser.error('slug must be lowercase kebab-case')
    repo = args.repo.resolve()
    if not (repo / '_config.yml').is_file() or not (repo / 'source/_posts').is_dir():
        parser.error('repo must be an existing Hexo blog with source/_posts')
    if not args.title.strip() or not args.description.strip():
        parser.error('title and description must not be empty')
    body = args.body_file.read_text(encoding='utf-8').strip()
    if not body or body.startswith('---'):
        parser.error('body must contain Markdown without front matter')
    quote = lambda value: json.dumps(value, ensure_ascii=False)
    now = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')
    header = f'---\ntitle: {quote(args.title.strip())}\ndate: {now}\ndescription: {quote(args.description.strip())}\ntags: {quote(list(dict.fromkeys(args.tags)))}\n---\n\n'
    target = repo / 'source/_posts' / (args.slug + '.md')
    try:
        with target.open('x', encoding='utf-8') as output:
            output.write(header + body + '\n')
    except FileExistsError:
        parser.error(f'note already exists: {target}')
    print(target)


if __name__ == '__main__':
    main()
