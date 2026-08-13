# Scaffold, verify, troubleshoot

## Scaffold with Drush (optional but fast)

```bash
ddev drush generate plugin:constraint   # alias: drush generate constraint
```

Answer the prompts (module, label, plugin id, and "Type of data to validate").
If unsure about the data type, pick anything and write your logic in
`validate()` afterwards. It generates the Constraint + Validator pair in
`src/Plugin/Validation/Constraint/`. Confirmed available on this site
(Drush 13).

## Make a new constraint take effect

Both the constraint **plugin** and any **field/entity definition** that
references it are cached. After adding either, rebuild:

```bash
ddev drush cr
```

`drush cr` rebuilds the container + all caches. If a full rebuild is blocked
(e.g. an unrelated broken service definition won't compile — see Troubleshooting
below), clear only the two caches that matter, without a container rebuild:

```bash
ddev drush php:eval '
\Drupal::service("validation.constraint")->clearCachedDefinitions();      // new/changed constraint plugin
\Drupal::service("entity_field.manager")->clearCachedFieldDefinitions();  // new field/entity constraint
'
```

## Verification harness (what was actually run here)

```bash
ddev drush php:eval '
\Drupal::service("validation.constraint")->clearCachedDefinitions();
\Drupal::service("entity_field.manager")->clearCachedFieldDefinitions();

$cases = [
  ["Bad Name!", 1],
  ["9front", 1],        // starts with a digit -> invalid
  ["views_ui", 0],
];
foreach ($cases as [$mn, $expect]) {
  $e = \Drupal\resources\Entity\ModuleDoc::create(["name" => "X", "machine_name" => $mn]);
  $v = $e->validate();
  $got = 0;
  foreach ($v as $x) { if ($x->getPropertyPath() === "machine_name") { $got++; } }
  printf("%-12s expect=%d got=%d %s\n", $mn, $expect, $got, $got === $expect ? "OK" : "FAIL");
}
'
```

Verified output on Drupal 11.3.11:

```
Bad Name!    expect=1 got=1 OK
9front       expect=1 got=1 OK
views_ui     expect=0 got=0 OK
```

The violation's property path is `machine_name` and the message is the
constraint's `$invalid` string.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Constraint validator ... not found` | Validator class isn't `<ConstraintClass>Validator` in the same namespace. Rename it, or override `validatedBy()` on the constraint to return the right class. |
| Constraint never fires | Caches not cleared after adding the plugin or the `addConstraint()`. Run `drush cr` (or the two-cache clear above). Also confirm the plugin `id` you passed to `addConstraint()` matches the `#[Constraint(id: ...)]`. |
| `The annotation @Constraint ... was never imported` | You're mixing the legacy annotation with attribute discovery, or missing a `use`. On D10/11 prefer the `#[Constraint]` attribute from `Drupal\Core\Validation\Attribute\Constraint`. |
| Error shows on the whole form, not the field | Default path for an entity-level constraint is the entity. Use `->buildViolation(...)->atPath('field_name')->addViolation()`. |
| `{{ value }}` shows literally in the message | Symfony placeholder syntax. Drupal uses `%value` / `@value` / `:value`; the constraint property + `addViolation()` params must match. |
| `drush cr` fails to compile the container ("Cannot autowire service … no such service exists") | An **unrelated** broken service definition. A container rebuild recompiles every service, so one bad definition blocks the whole rebuild. Fix that service (alias the missing interface to a real service id), or, to verify a constraint meanwhile, use the no-rebuild two-cache clear above. |
| Old `module_doc` rows now fail validation on edit | Expected — the new rule applies to existing data too. Fix the offending values or relax the constraint. |
