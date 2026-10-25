"""Global safeguards for the deterministic pytest suite."""

from pydantic_ai import models

# A test must opt into TestModel, FunctionModel, or an explicit fake. This makes
# an accidental real provider request fail immediately instead of contacting it.
models.ALLOW_MODEL_REQUESTS = False
