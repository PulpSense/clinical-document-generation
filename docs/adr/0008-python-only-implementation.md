# Keep the replacement implementation in Python

The replacement workflow will use Python as its only implementation language, with a small pinned dependency set permitted for document construction and XML handling. This preserves one maintainable runtime while allowing the rebuild to replace fragile regular-expression mutation of WordprocessingML.
