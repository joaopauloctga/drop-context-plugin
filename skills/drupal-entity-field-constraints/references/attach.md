# Attaching constraints — every target

A constraint plugin is inert until you attach it. *Where* you attach decides
what `$value` the validator receives and where the violation lands. Pick the
narrowest target that can express the rule.

| Target | `$value` in validator | How to attach |
|---|---|---|
| A base field (entity you own) | field item **list** | `->addConstraint('Id', [])` in `baseFieldDefinitions()` |
| A single field property | the **property** value | `->setPropertyConstraints('value', [...])` |
| A whole entity type (you own) | the **entity** | `constraints:` in the `#[ContentEntityType]` attribute |
| An entity type you don't own | the **entity** | `hook_entity_type_alter()` |
| A base field you don't own | field item **list** | `hook_entity_base_field_info_alter()` |
| A configurable (Field UI) field | field item **list** | `hook_entity_bundle_field_info_alter()` |

## 1. Base field on an entity your module defines

```php
// In YourEntity::baseFieldDefinitions().
$fields['machine_name'] = BaseFieldDefinition::create('string')
  ->setRequired(TRUE)
  ->addConstraint('ModuleDocMachineName', []);   // [] = no plugin options
```

If the constraint is configurable, pass options instead of `[]`:

```php
->addConstraint('Length', ['max' => 64]);
```

## 2. A single property of a field item

A field item can have several properties (`value`, `format`, `target_id`, …).
Constrain one directly — no custom plugin needed for the common cases:

```php
$fields['name'] = BaseFieldDefinition::create('string')
  ->setLabel(t('Name'))
  // Only the `value` property gets the Length constraint.
  ->setPropertyConstraints('value', ['Length' => ['max' => 32]]);
```

`setPropertyConstraints()` **replaces** all constraints on that property;
`addPropertyConstraints()` merges. The violation path becomes
`<field>.<delta>.<property>` (e.g. `name.0.value`).

## 3. A whole entity type your module defines (cross-field rules)

Cross-field rules (min ≤ max, start ≤ end, "if A then B required") can't live
on one field. Declare an **entity-level** constraint in the entity type. In
Drupal 11 that's the `constraints` key of the `#[ContentEntityType]` attribute:

```php
#[ContentEntityType(
  id: 'module_doc',
  // ...
  constraints: [
    'ModuleDocVersionRange' => [],   // plugin id => options
  ],
)]
class ModuleDoc extends EditorialContentEntityBase { /* ... */ }
```

The legacy annotation equivalent (Drupal 8/9, still supported):

```php
/**
 * @ContentEntityType(
 *   id = "module_doc",
 *   constraints = {
 *     "ModuleDocVersionRange" = {}
 *   }
 * )
 */
```

The entity-level validator receives the **entity** as `$value`, reads several
fields, and routes the violation to a field with `atPath()`:

```php
class ModuleDocVersionRangeConstraintValidator extends ConstraintValidator {
  public function validate(mixed $value, Constraint $constraint): void {
    if (!$value instanceof \Drupal\Core\Entity\ContentEntityInterface) {
      return;
    }
    if ($value->get('core_semver_minimum')->isEmpty() || $value->get('core_semver_maximum')->isEmpty()) {
      return;
    }
    $min = (int) $value->get('core_semver_minimum')->value;
    $max = (int) $value->get('core_semver_maximum')->value;
    if ($min > $max) {
      $this->context->buildViolation($constraint->outOfOrder)
        ->setParameter('%min', (string) $min)
        ->setParameter('%max', (string) $max)
        ->atPath('core_semver_maximum')   // render next to this widget
        ->addViolation();
    }
  }
}
```

## 4. An entity type you do NOT own (node, user, …)

Use `hook_entity_type_alter()` in your `.module` file to add an entity-level
constraint to someone else's entity:

```php
use Drupal\Core\Entity\EntityTypeInterface;

function mymodule_entity_type_alter(array &$entity_types): void {
  /** @var \Drupal\Core\Entity\EntityTypeInterface[] $entity_types */
  $entity_types['node']->addConstraint('MyNodeRule', []);
}
```

## 5. A base field you do NOT own

`hook_entity_base_field_info_alter()` lets you add a field-level constraint to a
core/base field (e.g. the user `name` field):

```php
use Drupal\Core\Entity\EntityTypeInterface;

function mymodule_entity_base_field_info_alter(array &$fields, EntityTypeInterface $entity_type): void {
  if ($entity_type->id() === 'user' && isset($fields['name'])) {
    $fields['name']->addConstraint('MyUsernameRule', []);
  }
}
```

## 6. A configurable (Field UI) field on a bundle

Fields added through the UI are *bundle* fields. Target them with
`hook_entity_bundle_field_info_alter()`:

```php
use Drupal\Core\Entity\EntityTypeInterface;

function mymodule_entity_bundle_field_info_alter(array &$fields, EntityTypeInterface $entity_type, string $bundle): void {
  if ($entity_type->id() === 'node' && $bundle === 'article' && isset($fields['field_subtitle'])) {
    $fields['field_subtitle']->addConstraint('MyRule', []);
    // or: $fields['field_subtitle']->setPropertyConstraints('value', ['Length' => ['max' => 80]]);
  }
}
```

> After adding any of these via a hook, clear caches (`drush cr`) so the altered
> field/entity definitions are rebuilt. See [verify.md](verify.md).

## Config entities (brief)

Config entities are validated against their **config schema**, not base-field
definitions. Add a `constraints:` key to a type/mapping in your module's
`config/schema/*.schema.yml`. That is a separate subsystem; see core's
`config/schema` examples (e.g. `FullyValidatableConstraint`).
