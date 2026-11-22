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
PIPELINE_VERSION = '3.1.1'
RULES_VERSION = '1.0.1'
PROMPT_VERSION = '1.1.0'


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


def canonical_solar_metric(name):
    aliases = {'power conversion efficiency': 'PCE', 'pce': 'PCE',
               'open-circuit voltage': 'Voc', 'open circuit voltage': 'Voc', 'voc': 'Voc',
               'short-circuit current density': 'Jsc', 'short circuit current density': 'Jsc', 'jsc': 'Jsc',
               'fill factor': 'FF', 'ff': 'FF', 'series resistance': 'Rs', 'rs': 'Rs',
               'shunt resistance': 'Rsh', 'rsh': 'Rsh', 'hysteresis index': 'HI', 'hi': 'HI',
               'stabilized pce': 'stabilized_PCE', 'retained pce': 'retained_PCE',
               'jsc_eqe': 'Jsc_EQE', 'stabilized_pce': 'stabilized_PCE', 'retained_pce': 'retained_PCE', 't80': 'T80'}
    return aliases.get(quote_normalize(name), name)


def canonical_unit(unit):
    if unit is None:
        return None
    unit = unicodedata.normalize('NFKC', unit).strip()
    return {'mA/cm^2': 'mA/cm2', 'mA cm-2': 'mA/cm2', 'mA cm−2': 'mA/cm2',
            'A/cm^2': 'A/cm2', 'Ω·cm2': 'Ohm*cm2', 'Ω cm2': 'Ohm*cm2',
            'Ohm cm2': 'Ohm*cm2', 'percent': '%', 'hours': 'h'}.get(unit, unit)


def scalar_number(raw):
    """Exact English scientific number syntax. A comma is accepted only in triadic grouping."""
    if raw is None:
        return None
    value = unicodedata.normalize('NFKC', str(raw)).strip().replace('\u2212', '-')
    if re.fullmatch(r'[+-]?[1-9]\d{0,2}(?:,\d{3})+(?:\.\d+)?(?:[eE][+-]?\d+)?', value):
        value = value.replace(',', '')
    # Lists, decimal-comma notation, boundaries, ranges and approximations stay raw.
    if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', value):
        return None
    return decimal_value(value)


def normalize_value(raw, unit, target):
    value = scalar_number(raw)
    if value is None and raw is not None and unit:
        source = unicodedata.normalize('NFKC', str(raw)).strip()
        # A model may preserve the explicit unit in raw_value as well as raw_unit.
        # Strip only that same trailing unit, never arbitrary words/qualifiers.
        for suffix in {unicodedata.normalize('NFKC', unit).strip(), canonical_unit(unit)}:
            if suffix and source.endswith(suffix):
                value = scalar_number(source[:-len(suffix)].strip())
                if value is not None:
                    break
    unit, target = canonical_unit(unit), canonical_unit(target)
    factors = {('mV', 'V'): '.001', ('fraction', '%'): '100', ('µm', 'nm'): '1000',
               ('um', 'nm'): '1000', ('mm2', 'cm2'): '.01', ('A/cm2', 'mA/cm2'): '1000',
               ('s', 'h'): str(Decimal(1) / 3600), ('min', 'h'): str(Decimal(1) / 60)}
    if value is None:
        return None
    if not unit and not target:
        return value  # Identity only; unknown units/scale remain unknown.
    if not unit or not target:
        return None
    if unit == target:
        return value
    return value * Decimal(factors[(unit, target)]) if (unit, target) in factors else None
