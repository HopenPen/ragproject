"""Reproduce PDF NUL ingestion checks. Optional PostgreSQL checks execute SELECT only; no model calls."""
import argparse
import hashlib
import json
from pathlib import Path
import fitz
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from app.config import settings
from app.db import engine
from app.storage import Storage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', action='append', type=Path, required=True)
    parser.add_argument('--postgres', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    storage, records = Storage(settings()), []
    for path in args.pdf:
        data = path.read_bytes()
        with fitz.open(stream=data, filetype='pdf') as pdf:
            affected = [i+1 for i, page in enumerate(pdf) if '\x00' in page.get_text()]
        if not affected:
            raise ValueError(f'{path.name}: no NUL in the original text layer')
        for number in affected:
            prepared = storage.prepare_page(data, number)
            assert '\x00' not in prepared['text'] and '\x00' in prepared['raw_text']
            assert '\x00' not in json.dumps(prepared['blocks'], ensure_ascii=False)
            record = {'pdf': str(path), 'sha256': hashlib.sha256(data).hexdigest(), 'page': number,
                      'nul_replacements': prepared['text_replacements']}
            if args.postgres:
                try:
                    with engine().connect() as conn:
                        conn.execute(text('SELECT CAST(:payload AS jsonb)'), {'payload': json.dumps({'text': prepared['raw_text']})})
                except DBAPIError as exc:
                    record['original_rejected_sqlstate'] = getattr(exc.orig, 'sqlstate', None)
                else:
                    raise AssertionError('Original NUL should be rejected by PostgreSQL jsonb')
                with engine().connect() as conn:
                    size, valid = conn.execute(text('SELECT octet_length(CAST(:body AS text)), CAST(:blocks AS jsonb) IS NOT NULL'),
                        {'body': prepared['text'], 'blocks': json.dumps(prepared['blocks'])}).one()
                    assert valid and size > 0
                    record.update(clean_text_bytes=size, postgres_accepts_clean_text_and_blocks=True)
            records.append(record)
    result = {'kind': 'source_pdf_text_storage_regression', 'database_mutations': False, 'model_calls': 0, 'pages': records}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
