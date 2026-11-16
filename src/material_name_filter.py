"""Literal material-name exclusions; orientation is deliberately not inferred."""
import unicodedata


def normalize_exclude_name(value):
    if not isinstance(value,str):raise ValueError('排除名称须为文字')
    value=unicodedata.normalize('NFKC',value).strip()
    if len(value)>80 or any(ord(c)<32 for c in value):raise ValueError('排除名称限一行、80 字以内')
    return value


def name_is_excluded(name,exclude_name):
    keyword=normalize_exclude_name(exclude_name)
    return bool(keyword and keyword.casefold() in unicodedata.normalize('NFKC',str(name)).casefold())
