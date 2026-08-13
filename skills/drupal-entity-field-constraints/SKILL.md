---
name: drupal-entity-field-constraints
description: >-
  Define and attach validation constraints on Drupal entities and fields to
  validate user input, protect data integrity, and enforce business rules. Use
  this skill to add a custom Constraint + Validator plugin, attach it to a base
  field, a field-item property, a whole entity type, or a configurable field,
  reuse core constraints (NotNull, Length, Range, Count, Email, AllowedValues,
  UniqueField), run `$entity->validate()`, or scaffold one with `drush generate`.
metadata:
  topic: Entity & Field Validation (Constraints) API
  core: ^10 || ^11
  verified_on: Drupal 11.3.11 (DDEV) — 2026-06-14
  worked_example: web/modules/custom/resources (ModuleDoc.machine_name)
---

# drupal-entity-field-constraints

Constraints are how Drupal validates entity/field data before it is saved. They
plug Symfony's Validator component into Drupal's plugin system: a **Constraint**
class declares the rule and its messages, a **Validator** class holds the logic,
and you **attach** the constraint to an entity type, a field, or a single field
property. Validation runs automatically on entity form submit and on
`$entity->save()`, and on demand via `$entity->validate()`.

> Paths below are relative to the Drupal site root (`drupal-site/`). The worked,
> verified example lives in the `resources` module and validates the
> `module_doc` entity's `machine_name` field.

## Key facts

| Property | Value |
|---|---|
| Plugin namespace | `Drupal\<module>\Plugin\Validation\Constraint` |
| Constraint base class | `Symfony\Component\Validator\Constraint` |
| Validator base class | `Symfony\Component\Validator\ConstraintValidator` |
| Discovery (D10/11) | `#[Constraint(id, label, type)]` attribute — **not** the legacy `@Constraint` annotation |
| Validator class name | `<ConstraintClass>Validator` by default (override `Constraint::validatedBy()`) |
| Message placeholders | Drupal `%placeholder` — **not** Symfony `{{ key }}` |
| Reference for the rule | the plugin **id** (e.g. `'ModuleDocMachineName'`, `'Range'`), not the class |

## When to use this skill

- **Reject malformed input on a field** (format, regex, allowed set) — e.g. a machine name.
- **Enforce a rule that spans two fields** (min ≤ max, start ≤ end) — needs an *entity-level* constraint.
- **Constrain a single property** of a multi-property field (e.g. max length of `value`).
- **Reuse core constraints** instead of writing code — `Length`, `Range`, `Count`, `Email`, `AllowedValues`, `NotNull`, `UniqueField`, `ValidReference`.
- **Add a constraint to an entity type your module does NOT own** (node, user, …) via an alter hook.

## The three steps (verified worked example)

This is the exact code that validates `module_doc.machine_name` on this site.

**Step 1 — Define the constraint** (`resources/src/Plugin/Validation/Constraint/ModuleDocMachineNameConstraint.php`):

```php
namespace Drupal\resources\Plugin\Validation\Constraint;

use Drupal\Core\StringTranslation\TranslatableMarkup;
use Drupal\Core\Validation\Attribute\Constraint;
use Symfony\Component\Validator\Constraint as SymfonyConstraint;

#[Constraint(
  id: 'ModuleDocMachineName',
  label: new TranslatableMarkup('Valid module machine name', [], ['context' => 'Validation']),
  type: 'string',
)]
class ModuleDocMachineNameConstraint extends SymfonyConstraint {
  // One public property per message. %value is a Drupal placeholder.
  public string $invalid = '%value is not a valid machine name. Use lowercase letters, numbers and underscores only, starting with a letter.';
}
```

**Step 2 — Write the validator** (same namespace, `…MachineNameConstraintValidator.php`):

```php
use Symfony\Component\Validator\Constraint;
use Symfony\Component\Validator\ConstraintValidator;

class ModuleDocMachineNameConstraintValidator extends ConstraintValidator {
  public function validate(mixed $value, Constraint $constraint): void {
    assert($constraint instanceof ModuleDocMachineNameConstraint);
    // Attached on a field, $value is the field item LIST — iterate items.
    foreach ($value as $item) {
      $string = (string) $item->value;
      if ($string !== '' && !preg_match('/^[a-z][a-z0-9_]*$/', $string)) {
        $this->context->addViolation($constraint->invalid, ['%value' => $string]);
      }
    }
  }
}
```

**Step 3 — Attach it** (in `ModuleDoc::baseFieldDefinitions()`, on the field):

```php
$fields['machine_name'] = BaseFieldDefinition::create('string')
  ->setRequired(TRUE)
  ->setSetting('max_length', 120)
  ->addConstraint('ModuleDocMachineName', []);   // empty array = no options
```

Other attachment targets (entity-level, property-level, configurable fields,
entities you don't own) are in [references/attach.md](references/attach.md).

## Run / verify (the driver)

A new constraint plugin and a new field constraint are **cached**, so they don't
take effect until caches are cleared. The normal way is `drush cr`. To verify
without a full container rebuild — clear just the two relevant caches, then
validate in-process. This is exactly what was run on this site:

```bash
ddev drush php:eval '
\Drupal::service("validation.constraint")->clearCachedDefinitions();
\Drupal::service("entity_field.manager")->clearCachedFieldDefinitions();
$bad = \Drupal\resources\Entity\ModuleDoc::create(["name" => "X", "machine_name" => "Bad Name!"]);
$good = \Drupal\resources\Entity\ModuleDoc::create(["name" => "X", "machine_name" => "views_ui"]);
printf("bad=%d good=%d\n", $bad->validate()->count(), $good->validate()->count());
'
```

Verified output: `bad=1 good=0`. The violation's property path is `machine_name`
and its message is the `$invalid` string. The full multi-case harness and the
`drush generate plugin:constraint` scaffold command are in
[references/verify.md](references/verify.md).

## Lazy-loaded references

- [references/attach.md](references/attach.md) — every way to attach a constraint: base fields, field-item properties (`setPropertyConstraints`), whole entity types you own (the `#[ContentEntityType(constraints: …)]` attribute), entity types you **don't** own and configurable fields (alter hooks `hook_entity_type_alter`, `hook_entity_base_field_info_alter`, `hook_entity_bundle_field_info_alter`).
- [references/cookbook.md](references/cookbook.md) — validator patterns: `buildViolation()->atPath()` to target a field/delta/property, singular vs plural messages with `setPlural()`, reading the field definition/label, entity-level (cross-field) validators, validating programmatically (`$entity->validate()`, `$entity->field_x->validate()`), and the property-path rules. Plus the catalog of reusable **core** constraints.
- [references/verify.md](references/verify.md) — `drush generate plugin:constraint`, the cache-clearing rules, the full verification harness, and troubleshooting (constraint "not firing", wrong field flagged, container-rebuild failures).

## Critical gotchas

1. **Drupal 10/11 uses the `#[Constraint]` attribute**, `Drupal\Core\Validation\Attribute\Constraint` — the `@Constraint` *annotation* in older docs/tutorials still works but is legacy. Match the host project; this codebase uses attributes everywhere.

2. **Messages use Drupal `%placeholder`, not Symfony `{{ key }}`.** Drupal swaps Symfony's translator for one that runs messages through `t()`. Stick to `%name` / `@name` / `%value`.

3. **A new constraint is cached — clear caches or it silently won't fire.** New plugin → `validation.constraint` plugin cache; new field constraint → `entity_field.manager` field-definition cache. `drush cr` does both; the verify snippet above clears only those two (useful when a full rebuild is blocked).

4. **Cross-field rules must be entity-level, not field-level.** A field validator only sees its own field. To compare two fields, declare the constraint in the entity type's `constraints` and read both fields off the entity (`$value` is the entity). See [references/attach.md](references/attach.md).

5. **Default property path is the field name; use `atPath()` to retarget.** For a field-list constraint the violation lands on the field (here: `machine_name`). For entity-level constraints, call `->buildViolation(...)->atPath('some_field')->addViolation()` so the error renders next to the right widget. Core's `ValidReferenceConstraintValidator` is the canonical example.

6. **The validator must be named `<ConstraintClass>Validator`** in the same namespace, or the constraint must override `validatedBy()`. A mismatch throws "Constraint validator not found".
