"""Create private, per-checkout credentials from the safe environment template."""
import os
from pathlib import Path
from secrets import token_hex


def main():
    root = Path(__file__).resolve().parents[1]
    credentials = {key: token_hex(24) for key in ('SESSION_SECRET', 'DEMO_PASSWORD', 'POSTGRES_PASSWORD')}
    template = (root / '.env.example').read_text(encoding='utf-8')
    lines = []
    for line in template.splitlines():
        key, _, _ = line.partition('=')
        lines.append(f'{key}={credentials[key]}' if key in credentials else line)
    try:
        handle = os.open(root / '.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print('Kept the existing .env. Open it privately to check local settings.')
        return
    with os.fdopen(handle, 'w', encoding='utf-8') as stream:
        stream.write('\n'.join(lines) + '\n')
    print('Created the ignored .env. Read DEMO_PASSWORD privately in your editor.')


if __name__ == '__main__':
    main()
