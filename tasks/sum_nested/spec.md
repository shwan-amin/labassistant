# Sum a nested list

Write a function `sum_nested(items)` that returns the sum of every integer in
`items`, where `items` is a list whose elements are either integers or lists
of the same kind. Lists can be nested to any depth.

```python
sum_nested([1, 2, 3])  # 6
sum_nested([1, [2, [3, 4]], 5])  # 15
sum_nested([[], [[]]])  # 0
sum_nested([])  # 0
```

Requirements:

- Use recursion.
- Do not modify the input list.
- Do not use global variables.
- Put your function in a file called `solution.py`.
