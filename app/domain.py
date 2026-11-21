# Назначение файла: чистые состояния, ошибки, ACL, единицы и source matching.
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4

PROFILES = ('solar-v1', 'rag-v1')
TERMINAL = {'succeeded', 'partially_succeeded', 'failed', 'cancelled', 'blocked_external_configuration'}
PIPELINE_VERSION = '3.0.0'
RULES_VERSION = '1.0.0'
PROMPT_VERSION = '1.0.2'


class Error(Exception):
    def __init__(self, status, code, message, details=None):
        self.status, self.code, self.message, self.details = status, code, message, details
        super().__init__(message)


class TransientError(Exception):
    pass


class ExternalConfiguration(Exception):
    pass


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def precondition(expected, actual):
    if expected is None:
        raise Error(428, 'precondition_required', 'If-Match is required')
    if expected.strip('"') != str(actual):
        raise Error(412, 'stale_revision', 'Revision changed', {'current_revision': actual})


def require_editor(actor):
    if actor['role'] not in ('editor', 'admin'):
        raise Error(403, 'forbidden', 'Editor role required')


def corpus_access(corpus, actor, write=False):
    if not corpus or (actor['role'] != 'admin' and corpus['owner_id'] != actor['id']):
        raise Error(404, 'not_found', 'Object not found')
    if write:
        require_editor(actor)
        if corpus['archived']:
            raise Error(409, 'corpus_archived', 'Corpus is archived')
    return corpus


def quote_normalize(value):
    value = unicodedata.normalize('NFKC', value).replace('\u00ad', '')
    value = re.sub(r'(?<=\w)-[ \t]*\r?\n[ \t]*(?=\w)', '', value)
    return re.sub(r'\s+', ' ', value).strip().casefold()


def decimal_value(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


UNITS = {'PCE': '%', 'FF': '%', 'HI': '%', 'stabilized_PCE': '%', 'retained_PCE': '%',
         'Voc': 'V', 'Jsc': 'mA/cm2', 'Jsc_EQE': 'mA/cm2', 'Rs': 'Ohm*cm2', 'Rsh': 'Ohm*cm2', 'T80': 'h'}


def normalize_value(raw, unit, target):
    # Boundaries, ranges and approximate values deliberately remain non-numeric.
    if raw is None or not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', str(raw).strip()):
        return None
    value = decimal_value(raw)
    factors = {('mV', 'V'): '.001', ('fraction', '%'): '100', ('µm', 'nm'): '1000',
               ('um', 'nm'): '1000', ('mm2', 'cm2'): '.01', ('A/cm2', 'mA/cm2'): '1000',
               ('s', 'h'): str(Decimal(1) / 3600), ('min', 'h'): str(Decimal(1) / 60)}
    if value is None or not unit or not target:
        return None
    if unit == target:
        return value
    return value * Decimal(factors[(unit, target)]) if (unit, target) in factors else None
