# Validator cookbook + reusable core constraints

## Reuse core constraints before writing one

Most rules are already a core plugin. Combine these (via `addConstraint`,
`setPropertyConstraints`, or inside a `Collection`) before building a custom
plugin:

| Plugin id | Purpose | Common options |
|---|---|---|
| `NotNull` / `NotBlank` | value/required | — |
| `IsNull` | must be empty | — |
| `Length` | string length | `min`, `max` |
| `Range` | numeric range | `min`, `max` |
| `Count` | number of items (cardinality) | `min`, `max` |
| `Email` | valid email | — |
| `AllowedValues` | value in a set | `choices` (or list field's allowed values) |
| `Regex` | matches a pattern | `pattern` |
| `UniqueField` | field value unique across entities | — |
| `ValidReference` | entity-reference target is valid/accessible | — |
| `ComplexData` | nest constraints onto a complex value's properties | `properties` |

```php
// No custom plugin needed:
->addConstraint('Length', ['max' => 64])
->setPropertyConstraints('value', ['Regex' => ['pattern' => '/^[a-z0-9_]+$/']])
->addConstraint('UniqueField', [])           // value must be unique entity-wide
```

A custom plugin is only warranted when the rule needs logic the core plugins
can't express (DB lookups, cross-field comparisons, service calls).

## Pattern: target a specific field / delta / property

The default property path of a field constraint is the **field name**. To flag a
specific delta or property — or, from an entity-level constraint, a specific
field — use `buildViolation()->atPath()`:

```php
$this->context->buildViolation($constraint->message)
  ->atPath('0.value')          // delta 0, the value property
  ->setParameter('%value', $bad)
  ->addViolation();
```

Core's `ValidReferenceConstraintValidator::validate()` is the reference example
for `atPath()` usage.

## Pattern: singular vs plural messages

Write the message with a pipe between forms, then call `setPlural()`:

```php
// In the constraint class:
public string $errorMessage = '%field must have at least %count value.|%field must have at least %count values.';

// In the validator:
if (count($value) < $constraint->count) {
  $this->context->buildViolation($constraint->errorMessage)
    ->setParameter('%field', $value->getFieldDefinition()->label())
    ->setParameter('%count', (string) $constraint->count)
    ->setPlural((int) $constraint->count)   // chooses singular/plural form
    ->addViolation();
}
```

## Pattern: read the field definition / label

When the validator is attached to a field item list, `$value` is the
`FieldItemListInterface`:

```php
$label = $value->getFieldDefinition()->label();
$entity = $value->getEntity();              // the host entity, if you need siblings
```

## `addViolation()` vs `buildViolation()`

- `addViolation($message, $params)` — quick, attaches to the current path.
- `buildViolation($message)->setParameter(...)->atPath(...)->setPlural(...)->addViolation()`
  — the builder; use it whenever you need `atPath`, `setPlural`, or a custom code.

## Validating programmatically

Validation is automatic on entity form submit and on `$entity->save()`. Trigger
it manually anywhere:

```php
// Whole entity → ConstraintViolationListInterface.
$violations = $entity->validate();

// One field only.
$violations = $entity->get('machine_name')->validate();

foreach ($violations as $violation) {
  $path = $violation->getPropertyPath();      // e.g. "machine_name" or "machine_name.0.value"
  $msg  = (string) $violation->getMessage();
}
```

**Property-path rules** (relative to where validation began):
- `$entity->field_text->validate()` → path like `0.value`.
- `$entity->validate()` → path like `field_text.0.value`.
- A field-list-level `addViolation()` → path is just the field name.

> `$entity->validate()` does **not** block `save()` on its own. Entity *forms*
> turn violations into form errors; the storage layer does not re-run validation.
> If you save entities from custom code and want the rules enforced, call
> `validate()` yourself and handle the result.
