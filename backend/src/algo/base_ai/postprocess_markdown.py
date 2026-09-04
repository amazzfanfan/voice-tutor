import re
from html.parser import HTMLParser
from typing import List, Dict, Tuple

# --------------------------------------------------
# 增强版：先展开合并单元格，再生成 Markdown
# --------------------------------------------------
class MergedTableParser(HTMLParser):
    """
    将含 rowspan/colspan 的 HTML 表格展开成二维列表，
    再输出对齐的 Markdown 表格。
    """
    def __init__(self):
        super().__init__()
        self._matrix: List[List[str]] = []   # 二维内容矩阵
        self._row_idx = 0                    # 当前行指针
        self._col_idx = 0                    # 当前列指针
        self._span_info: Dict[Tuple[int, int], Tuple[int, int]] = {}
        # 临时变量
        self._tag_stack = []
        self._cur_cell_text = []
        self._cur_rowspan = 1
        self._cur_colspan = 1

    def handle_starttag(self, tag, attrs):
        self._tag_stack.append(tag)
        if tag == 'tr':
            # 换行前，先根据 span_info 占位
            self._apply_span_shift()
            self._col_idx = 0
        elif tag in ('td', 'th'):
            self._cur_cell_text = []
            attrs_dict = dict(attrs)
            self._cur_rowspan = int(attrs_dict.get('rowspan', 1))
            self._cur_colspan = int(attrs_dict.get('colspan', 1))

    def handle_endtag(self, tag):
        if self._tag_stack and self._tag_stack[-1] == tag:
            self._tag_stack.pop()
        if tag in ('td', 'th'):
            # 找到第一个非占位列
            while (self._row_idx, self._col_idx) in self._span_info:
                self._col_idx += 1
            # 填充内容
            text = ''.join(self._cur_cell_text).strip() or '&nbsp;'
            for dr in range(self._cur_rowspan):
                for dc in range(self._cur_colspan):
                    r, c = self._row_idx + dr, self._col_idx + dc
                    if dr == 0 and dc == 0:
                        self._ensure_matrix(r, c)
                        self._matrix[r][c] = text
                    else:
                        self._span_info[(r, c)] = (0, 0)  # 占位标记
            self._col_idx += self._cur_colspan
        elif tag == 'tr':
            self._row_idx += 1

    def handle_data(self, data):
        if self._tag_stack and self._tag_stack[-1] in ('td', 'th'):
            self._cur_cell_text.append(data)

    def _ensure_matrix(self, r, c):
        while len(self._matrix) <= r:
            self._matrix.append([])
        while len(self._matrix[r]) <= c:
            self._matrix[r].append('')

    def _apply_span_shift(self):
        # 如果当前行某些列被上一行 rowspan 占用，自动跳过
        c = 0
        while (self._row_idx, c) in self._span_info:
            c += 1

    def markdown(self) -> str:
        if not self._matrix:
            return ''
        # 补齐每行列数
        max_cols = max(len(row) for row in self._matrix)
        for row in self._matrix:
            row += [''] * (max_cols - len(row))
        md = ['| ' + ' | '.join(row) + ' |' for row in self._matrix]
        sep = '|' + '|'.join('-' * max_cols) + '|'
        md.insert(1, sep)
        return '\n'.join(md)

def _html_table_to_md(html: str) -> str:
    p = MergedTableParser()
    p.feed(html)
    return p.markdown()

# --------------------------------------------------
# 图片处理（与之前相同）
# --------------------------------------------------
_IMG_RE = re.compile(r'<img\s+[^>]*>', re.I)
def _img_sub(m: re.Match) -> str:
    tag = m.group(0)
    src   = re.search(r'src=["\'](.*?)["\']',   tag, re.I)
    alt   = re.search(r'alt=["\'](.*?)["\']',   tag, re.I)
    title = re.search(r'title=["\'](.*?)["\']', tag, re.I)
    return '![{alt}]({src}{title})'.format(
        alt=alt.group(1) if alt else '',
        src=src.group(1) if src else '',
        title=f' "{title.group(1)}"' if title else '')


# 1. 块级元素：用双换行代替
_BLOCK_TAGS = {'div', 'p', 'section', 'article', 'header', 'footer', 'main', 'nav', 'aside'}
# 2. 内换行：<br> → 两个空格 + 换行
_BR_RE = re.compile(r'<br\s*/?>', re.I)

def _sanitize_remaining_html(html: str) -> str:
    # 先处理 <br>
    html = _BR_RE.sub('  \n', html)
    # 再处理块级标签：整 tag 替换成双换行
    for tag in _BLOCK_TAGS:
        html = re.sub(rf'</?{tag}[^>]*>', '\n\n', html, flags=re.I)
    # 最后剥除所有剩余标签
    html = re.sub(r'<[^>]+>', '', html)
    # 合并多余空行
    html = re.sub(r'\n{3,}', '\n\n', html)
    return html.strip()


# --------------------------------------------------
# 唯一对外接口
# --------------------------------------------------
def html_to_md(html: str) -> str:
    # 1. 图片
    html = _IMG_RE.sub(_img_sub, html)
    # 2. 表格（含合并单元格、空单元格 &nbsp;）
    html = re.sub(r'<table[^>]*>.*?</table>', lambda m: _html_table_to_md(m.group(0)), html, flags=re.I | re.S)
    # 3. 剩余标签（含 div、p、br 等）
    html = _sanitize_remaining_html(html)
    return html