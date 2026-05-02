# PlatformGen Python

Standalone Python/Desktop product repo for the PlatformGen morph from Auger.

## Current intent

This repo is the future home of the standalone Python-based PlatformGen product.
It starts as a planning and migration boundary, not an in-place rename of Auger.

## Guardrails

- **Auger stays protected and working** during this transition.
- **`~/.auger` is protected source state** until migration is explicit and tested.
- **PlatformGen-web `/hub` stays functional** but is not the main design center yet.
- **Migration first, rebrand second**: dual-read or copy-forward state handling before any destructive rename.

## Initial scope

1. Define repo boundaries between Auger, `platformgen`, `platformgen-web`, and `platformgen-py`.
2. Design state migration from `~/.auger` to future PlatformGen-owned paths.
3. Split Python packaging from host/bootstrap installation concerns.
4. Establish PlatformGen as the product/factory layer, with Auger as a protected work-branded deployment.

## Near-term direction

- Build the standalone Python/Desktop product here.
- Treat the current `platformgen` repo as a migration/reference source.
- Port selected concepts and widgets to the web product after the Python/Desktop shape is stable.
