#!/usr/bin/env python3
from __future__ import annotations

import re

_TOKEN = re.compile(
    r"\s*(?:(0[xX][0-9A-Fa-f]+|[0-9]+)|([A-Za-z_][A-Za-z0-9_]*)|"
    r"(\|\||&&|==|!=|<=|>=|<<|>>|[()!~+\-*/%<>&^|]))"
)
_BINARY_PRECEDENCE = {
    "||": 1, "&&": 2, "|": 3, "^": 4, "&": 5,
    "==": 6, "!=": 6, "<": 7, "<=": 7, ">": 7, ">=": 7,
    "<<": 8, ">>": 8, "+": 9, "-": 9, "*": 10, "/": 10, "%": 10,
}
_UNARY = {"!", "~", "+", "-"}


def tokenize(expression: str) -> list[str]:
    tokens: list[str] = []
    position = 0
    while position < len(expression):
        match = _TOKEN.match(expression, position)
        if not match:
            raise ValueError(f"unsupported token at offset {position}")
        tokens.append(next(group for group in match.groups() if group is not None))
        position = match.end()
    return tokens


class _Parser:
    def __init__(self, tokens: list[str], variables: set[str]):
        self.tokens = tokens
        self.variables = variables
        self.position = 0

    def peek(self) -> str | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def take(self) -> str:
        token = self.peek()
        if token is None:
            raise ValueError("unexpected end of expression")
        self.position += 1
        return token

    def expression(self, minimum: int = 1) -> None:
        token = self.take()
        if token in _UNARY:
            self.expression(11)
        elif token == "(":
            self.expression()
            if self.take() != ")":
                raise ValueError("unbalanced parentheses")
        elif re.fullmatch(r"0[xX][0-9A-Fa-f]+|[0-9]+", token):
            pass
        elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token) and token in self.variables:
            pass
        else:
            raise ValueError(f"unknown identifier or invalid primary: {token}")
        while self.peek() in _BINARY_PRECEDENCE and _BINARY_PRECEDENCE[self.peek()] >= minimum:
            operator = self.take()
            self.expression(_BINARY_PRECEDENCE[operator] + 1)


def is_pure_expression(expression: str, variables: set[str]) -> bool:
    try:
        tokens = tokenize(expression)
        if not tokens:
            return False
        parser = _Parser(tokens, variables)
        parser.expression()
        return parser.position == len(tokens)
    except ValueError:
        return False
