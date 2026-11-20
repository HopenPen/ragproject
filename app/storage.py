# Назначение файла: private S3, PDF inspection, PyMuPDF renders/crops, tables и OCR.
import hashlib
import io
import json
import boto3
import fitz
import pdfplumber
import pytesseract
from PIL import Image
from botocore.config import Config
from botocore.exceptions import ClientError
from app.domain import Error, ExternalConfiguration


class ReadCache:
    def __init__(self, url):
        import redis
        self.client = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)

    def get(self, key):
        import redis
        try:
            value = self.client.get(key)
            return json.loads(value) if value else None
        except (redis.RedisError, ValueError):
            return None

    def put(self, key, value, ttl=30):
        import redis
        try:
            self.client.setex(key, ttl, json.dumps(value, ensure_ascii=False))
        except redis.RedisError:
            pass


class Storage:
    def __init__(self, config):
        self.config = config
        self.client = boto3.client('s3', endpoint_url=config.s3_endpoint,
            aws_access_key_id=config.s3_access_key.get_secret_value(), aws_secret_access_key=config.s3_secret_key.get_secret_value(),
            region_name='us-east-1', config=Config(connect_timeout=5, read_timeout=30, retries={'max_attempts': 2}, s3={'addressing_style': 'path'}))

    def initialize(self):
        try:
            self.client.head_bucket(Bucket=self.config.s3_bucket)
        except ClientError as exc:
            if exc.response['Error']['Code'] not in ('404', 'NoSuchBucket'):
                raise
            self.client.create_bucket(Bucket=self.config.s3_bucket)

    def put(self, key, data, content_type):
        self.client.put_object(Bucket=self.config.s3_bucket, Key=key, Body=data, ContentType=content_type,
                               Metadata={'sha256': hashlib.sha256(data).hexdigest()})

    def get(self, key):
        response = self.client.get_object(Bucket=self.config.s3_bucket, Key=key)
        data = response['Body'].read()
        expected = response.get('Metadata',{}).get('sha256')
        if not expected or hashlib.sha256(data).hexdigest() != expected:
            raise Error(502, 'storage_integrity', 'Stored object checksum mismatch')
        return data

    def inspect_pdf(self, data):
        if len(data) > self.config.max_pdf_bytes:
            raise Error(413, 'pdf_too_large', 'PDF exceeds configured byte limit')
        if not data.startswith(b'%PDF-'):
            raise Error(415, 'invalid_pdf', 'PDF signature required')
        try:
            with fitz.open(stream=data, filetype='pdf') as pdf:
                if pdf.is_encrypted or pdf.needs_pass:
                    raise Error(422, 'encrypted_pdf', 'Encrypted PDF is not supported')
                if not 0 < len(pdf) <= self.config.max_pdf_pages:
                    raise Error(413, 'page_limit', 'PDF page count exceeds configured limit')
                pages = [{'number': i+1, 'width': p.rect.width, 'height': p.rect.height} for i, p in enumerate(pdf)]
                return {'page_count': len(pdf), 'pages': pages, 'sha256': hashlib.sha256(data).hexdigest()}
        except Error:
            raise
        except Exception:
            raise Error(422, 'unreadable_pdf', 'PDF cannot be read')

    def prepare_page(self, data, number):
        with fitz.open(stream=data, filetype='pdf') as pdf:
            page = pdf[number-1]
            pix = page.get_pixmap(dpi=self.config.render_dpi, alpha=False)
            png = pix.tobytes('png')
            blocks = [{'bbox': list(b[:4]), 'text': b[4]} for b in page.get_text('blocks') if b[6] == 0]
            text = page.get_text()
            needs_ocr = len(text.strip()) < 40
            ocr_error = None
            ocr_text = ''
            if needs_ocr:
                try:
                    ocr_text = pytesseract.image_to_string(Image.open(io.BytesIO(png)), lang='eng+rus', timeout=120)
                    text = ocr_text
                except (pytesseract.TesseractNotFoundError, RuntimeError) as exc:
                    raise ExternalConfiguration('Tesseract eng/rus is unavailable') from exc
            crops = []
            # Every image is rendered even on pages that already have a text layer.
            for i, image in enumerate(page.get_image_info()):
                bbox = fitz.Rect(image['bbox']) & page.rect
                if not bbox.is_empty:
                    crops.append({'name': f'image-{i}', 'bbox': list(bbox),
                                  'data': page.get_pixmap(clip=bbox, dpi=self.config.render_dpi, alpha=False).tobytes('png')})
            with pdfplumber.open(io.BytesIO(data)) as tables_pdf:
                try:
                    tables = tables_pdf.pages[number-1].extract_tables()
                except (ValueError, TypeError):
                    tables = []
            return {'number': number, 'width': page.rect.width, 'height': page.rect.height, 'text': text,
                    'blocks': blocks, 'png': png, 'ocr': needs_ocr, 'engine': 'tesseract+PyMuPDF' if needs_ocr else 'PyMuPDF',
                    'coverage': 'complete', 'tables': tables, 'crops': crops, 'ocr_text': ocr_text}
