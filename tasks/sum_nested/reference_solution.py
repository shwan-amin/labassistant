def sum_nested(items: list) -> int:
    """Return the sum of all integers in an arbitrarily nested list."""
    total = 0
    for item in items:
        if isinstance(item, list):
            # Recursive case: a sublist is a smaller instance of the same problem.
            total += sum_nested(item)
        else:
            # Base case: a plain integer contributes its own value.
            total += item
    return total
