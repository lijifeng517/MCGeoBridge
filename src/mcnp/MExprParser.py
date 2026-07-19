from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional


FACET_ID_BASE = 1_000_000_000


def encode_facet_id(surface_id: int, facet_id: int) -> int:
    return FACET_ID_BASE + int(surface_id) * 100 + int(facet_id)


def decode_facet_id(value: int):
    if value < FACET_ID_BASE:
        return None
    packed = value - FACET_ID_BASE
    return packed // 100, packed % 100


class ExprNode:
    def to_dict(self) -> dict:
        raise NotImplementedError()


@dataclass(frozen=True)
class SurfaceRef(ExprNode):
    sid: int
    sense: int  # -1 for inside (negative), +1 for outside (positive)

    def to_dict(self) -> dict:
        return {"type": "surface", "sid": self.sid, "sense": self.sense}


@dataclass(frozen=True)
class CellRef(ExprNode):
    cid: int

    def to_dict(self) -> dict:
        return {"type": "cell", "cid": self.cid}


@dataclass(frozen=True)
class UnionNode(ExprNode):
    left: ExprNode
    right: ExprNode

    def to_dict(self) -> dict:
        return {"type": "union", "left": self.left.to_dict(), "right": self.right.to_dict()}


@dataclass(frozen=True)
class IntersectionNode(ExprNode):
    left: ExprNode
    right: ExprNode

    def to_dict(self) -> dict:
        return {"type": "intersection", "left": self.left.to_dict(), "right": self.right.to_dict()}


@dataclass(frozen=True)
class ComplementNode(ExprNode):
    child: ExprNode

    def to_dict(self) -> dict:
        return {"type": "complement", "child": self.child.to_dict()}


class _Token:
    def __init__(self, kind: str, value=None):
        self.kind = kind
        self.value = value

    def __repr__(self):
        return f"_Token({self.kind}, {self.value})"


def _tokenize(expr: str) -> List[_Token]:
    tokens: List[_Token] = []
    i = 0
    n = len(expr)
    while i < n:
        ch = expr[i]
        if ch.isspace():
            i += 1
            continue
        if ch in "():#":
            tokens.append(_Token(ch))
            i += 1
            continue
        if ch in "+-" or ch.isdigit():
            sign = 1
            if ch in "+-":
                sign = -1 if ch == "-" else 1
                i += 1
                if i >= n or not expr[i].isdigit():
                    raise ValueError(f"Invalid surface id near position {i} in '{expr}'")
            j = i
            while j < n and expr[j].isdigit():
                j += 1
            surface_id = int(expr[i:j])
            if j < n and expr[j] == '.' and j + 1 < n and expr[j + 1].isdigit():
                k = j + 1
                while k < n and expr[k].isdigit():
                    k += 1
                facet_id = int(expr[j + 1:k])
                val = encode_facet_id(surface_id, facet_id) * sign
                j = k
            else:
                val = surface_id * sign
            tokens.append(_Token("INT", val))
            i = j
            continue
        raise ValueError(f"Unexpected character '{ch}' in geometry expression: '{expr}'")
    return tokens


class _Parser:
    def __init__(self, tokens: List[_Token]):
        self.tokens = tokens
        self.pos = 0

    def _peek(self) -> Optional[_Token]:
        if self.pos >= len(self.tokens):
            return None
        return self.tokens[self.pos]

    def _next(self) -> Optional[_Token]:
        tok = self._peek()
        if tok is not None:
            self.pos += 1
        return tok

    def _expect(self, kind: str) -> _Token:
        tok = self._next()
        if tok is None or tok.kind != kind:
            raise ValueError(f"Expected '{kind}' but got '{tok}'")
        return tok

    def parse(self) -> ExprNode:
        node = self._parse_union()
        if self._peek() is not None:
            raise ValueError(f"Unexpected token '{self._peek()}' at end of expression")
        return node

    def _parse_union(self) -> ExprNode:
        node = self._parse_intersection()
        while True:
            tok = self._peek()
            if tok is not None and tok.kind == ":":
                self._next()
                rhs = self._parse_intersection()
                node = UnionNode(node, rhs)
            else:
                break
        return node

    def _parse_intersection(self) -> ExprNode:
        node = self._parse_factor()
        while True:
            tok = self._peek()
            if tok is not None and (tok.kind == "INT" or tok.kind == "(" or tok.kind == "#"):
                rhs = self._parse_factor()
                node = IntersectionNode(node, rhs)
            else:
                break
        return node

    def _parse_factor(self) -> ExprNode:
        tok = self._peek()
        if tok is None:
            raise ValueError("Unexpected end of expression")
        if tok.kind == "#":
            self._next()
            nxt = self._peek()
            if nxt is not None and nxt.kind == "INT":
                # MCNP '#N' means complement of cell N.
                val = self._next().value
                return ComplementNode(CellRef(abs(val)))
            node = self._parse_factor()
            return ComplementNode(node)
        if tok.kind == "INT":
            val = self._next().value
            sid = abs(val)
            sense = -1 if val < 0 else 1
            return SurfaceRef(sid, sense)
        if tok.kind == "(":
            self._next()
            node = self._parse_union()
            self._expect(")")
            return node
        raise ValueError(f"Unexpected token '{tok}'")


def _normalize_expr(expr: str) -> str:
    def has_top_level_colon(s: str) -> bool:
        depth = 0
        for ch in s:
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            elif ch == ':' and depth == 0:
                return True
        return False

    def split_top_level_colon(s: str) -> List[str]:
        depth = 0
        start = 0
        parts = []
        for i, ch in enumerate(s):
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            elif ch == ':' and depth == 0:
                parts.append(s[start:i])
                start = i + 1
        parts.append(s[start:])
        return parts

    i = 0
    n = len(expr)
    out = []
    while i < n:
        ch = expr[i]
        if ch == '(':
            depth = 1
            j = i + 1
            while j < n and depth > 0:
                if expr[j] == '(':
                    depth += 1
                elif expr[j] == ')':
                    depth -= 1
                j += 1
            if depth != 0:
                raise ValueError(f"Unbalanced parentheses in geometry expression: '{expr}'")
            inner = expr[i + 1 : j - 1]
            norm_inner = _normalize_expr(inner)

            k = i - 1
            while k >= 0 and expr[k].isspace():
                k -= 1
            prefixed_hash = k >= 0 and expr[k] == '#'

            if has_top_level_colon(inner) and not prefixed_hash:
                parts = split_top_level_colon(norm_inner)
                parts = [f"#({p.strip()})" for p in parts if p.strip() != ""]
                norm_inner = " ".join(parts)
                out.append("#(" + norm_inner + ")")
            else:
                out.append("(" + norm_inner + ")")
            i = j
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def normalize_geom_expr(expr: str) -> str:
    return _normalize_expr(expr)


def parse_geom_expr(expr: str) -> ExprNode:
    expr = _normalize_expr(expr)
    tokens = _tokenize(expr)
    parser = _Parser(tokens)
    return simplify_expr(parser.parse())


def simplify_expr(node: ExprNode) -> ExprNode:
    if isinstance(node, SurfaceRef):
        return node
    if isinstance(node, CellRef):
        return node
    if isinstance(node, ComplementNode):
        child = simplify_expr(node.child)
        if isinstance(child, SurfaceRef):
            return SurfaceRef(child.sid, -child.sense)
        if isinstance(child, ComplementNode):
            return simplify_expr(child.child)
        return ComplementNode(child)
    if isinstance(node, UnionNode):
        return UnionNode(simplify_expr(node.left), simplify_expr(node.right))
    if isinstance(node, IntersectionNode):
        return IntersectionNode(simplify_expr(node.left), simplify_expr(node.right))
    return node


def _collect_intersection_surfaces(node):
    if isinstance(node, SurfaceRef):
        return [node]
    if isinstance(node, IntersectionNode):
        left = _collect_intersection_surfaces(node.left)
        right = _collect_intersection_surfaces(node.right)
        if left is None or right is None:
            return None
        return left + right
    return None


def _fmt_surface(sid: int, sense: int, include_plus: bool = False) -> str:
    if sense < 0:
        return f"-{sid}"
    return f"+{sid}" if include_plus else f"{sid}"


def expr_to_str(node: ExprNode, parent_prec: int = 0) -> str:
    # precedence: union=1, intersection=2, complement/surface=3
    if isinstance(node, SurfaceRef):
        return _fmt_surface(node.sid, node.sense, include_plus=False)
    if isinstance(node, CellRef):
        return f"CELL({node.cid})"

    if isinstance(node, ComplementNode):
        child = node.child
        if isinstance(child, SurfaceRef):
            return _fmt_surface(child.sid, -child.sense, include_plus=False)
        if isinstance(child, CellRef):
            return f"#{child.cid}"

        inter_surfs = _collect_intersection_surfaces(child)
        if inter_surfs is not None:
            parts = []
            for s in inter_surfs:
                parts.append(_fmt_surface(s.sid, -s.sense, include_plus=False))
            return "#(" + " ".join(parts) + ")"

        inner = expr_to_str(child, parent_prec=3)
        return "#(" + inner + ")"

    if isinstance(node, UnionNode):
        left = expr_to_str(node.left, parent_prec=1)
        right = expr_to_str(node.right, parent_prec=1)
        s = f"{left} : {right}"
        if parent_prec > 1:
            return "(" + s + ")"
        return s

    if isinstance(node, IntersectionNode):
        left = expr_to_str(node.left, parent_prec=2)
        right = expr_to_str(node.right, parent_prec=2)
        s = f"{left} {right}"
        if parent_prec > 2:
            return "(" + s + ")"
        return s

    return str(node)


def collect_surface_ids(node: ExprNode, out: Optional[set] = None) -> set:
    if out is None:
        out = set()
    if isinstance(node, SurfaceRef):
        out.add(node.sid)
    elif isinstance(node, CellRef):
        pass
    elif isinstance(node, UnionNode) or isinstance(node, IntersectionNode):
        collect_surface_ids(node.left, out)
        collect_surface_ids(node.right, out)
    elif isinstance(node, ComplementNode):
        collect_surface_ids(node.child, out)
    return out
