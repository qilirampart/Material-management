"""Literal material-name exclusions; orientation is deliberately not inferred."""
import re
import unicodedata
from dataclasses import dataclass

DEFAULT_INCLUDE_NAME = '二创, 精剪原片'


def normalize_exclude_name(value):
    if not isinstance(value,str):raise ValueError('排除名称须为文字')
    value=unicodedata.normalize('NFKC',value).strip()
    if len(value)>80 or any(ord(c)<32 for c in value):raise ValueError('排除名称限一行、80 字以内')
    return value


def name_is_excluded(name,exclude_name):
    keyword=normalize_exclude_name(exclude_name)
    return bool(keyword and keyword.casefold() in unicodedata.normalize('NFKC',str(name)).casefold())


def normalize_name_terms(value):
    if not isinstance(value,str):
        raise ValueError('名称筛选须为文字')
    value=unicodedata.normalize('NFKC',value).strip()
    if len(value)>160 or any(ord(c)<32 for c in value):
        raise ValueError('名称筛选限一行、160 字以内')
    terms={}
    for field in re.split(r'[,;、]', value):
        term=field.strip()
        if len(term)>80:
            raise ValueError('单个关键词限 80 字以内')
        if term:
            terms.setdefault(term.casefold(),term)
    if len(terms)>10:
        raise ValueError('每项最多填写 10 个关键词')
    if len(', '.join(terms.values()))>160:
        raise ValueError('名称筛选限 160 字以内')
    return tuple(terms.values())


@dataclass(frozen=True)
class NameFilter:
    include: tuple
    exclude: tuple

    @classmethod
    def for_batch(cls,state,*,query=False):
        if 'include_name' in state:
            return cls(normalize_name_terms(state['include_name']),normalize_name_terms(state.get('exclude_name','')))
        # Preserve the old download and scheduled-query contracts.
        legacy=normalize_exclude_name(state.get('exclude_name',''))
        return cls(normalize_name_terms(DEFAULT_INCLUDE_NAME) if query else (), (legacy,) if legacy else ())

    def reason(self,name):
        value=unicodedata.normalize('NFKC',str(name)).casefold()
        if any(term.casefold() in value for term in self.exclude):
            return '名称已排除'
        if self.include and not any(term.casefold() in value for term in self.include):
            return '未命中包含词'
        return ''
