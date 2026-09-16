# Lab: Expression evaluator

Arithmetic expressions have a recursive structure: `2 * (3 + 4)` is a
multiplication whose right-hand side is itself an expression. In this lab you
will parse expressions into a tree and then **recursively** evaluate and print
that tree.

## Grammar

```
expression := term (("+" | "-") term)*
term       := factor (("*" | "/") factor)*
factor     := NUMBER | "-" factor | "(" expression ")"
```

Operators are left-associative, so `8 - 3 - 2` means `(8 - 3) - 2`.

## Files

| File | What it contains |
|---|---|
| `tokens.py` | `tokenize(text)`: splits text into tokens (provided). |
| `nodes.py` | AST node classes `Number`, `Negate`, `BinaryOp` (provided). |
| `parser.py` | `parse(text)`: a recursive-descent parser that returns an AST. |
| `evaluator.py` | `evaluate(node)` and `count_operations(node)`. |
| `printer.py` | `to_text(node)`: turns an AST back into a fully bracketed string. |

## Tasks

1. **`parse(text)`**: implement `parse_expression`, `parse_term` and
   `parse_factor` following the grammar. Raise `ParseError` for invalid input,
   including unmatched brackets and leftover tokens.
2. **`evaluate(node)`**: compute the value of an AST. `/` is true division.
   Raise `EvaluationError` for division by zero.
3. **`count_operations(node)`**: the number of `BinaryOp` and `Negate` nodes.
4. **`to_text(node)`**: numbers print as-is, `Negate` prints as `(-x)`, and a
   `BinaryOp` prints as `(left op right)`.

`evaluate`, `count_operations` and `to_text` must be recursive. Do not use
Python's `eval`. Run the tests with `pytest` from this folder.
