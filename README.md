# Motionile

Motionile is a project by [The GenAI Labs](https://github.com/The-GenAI-Labs).

## Branching strategy

| Branch    | Purpose                                                            |
| --------- | ------------------------------------------------------------------ |
| `init`    | Initial project setup snapshot.                                    |
| `develop` | Integration branch for ongoing work. Feature branches merge here.  |
| `prod`    | Production-ready code. Only receives tested merges from `develop`. |

### Workflow

1. Create a feature branch from `develop`:
   ```bash
   git checkout develop
   git pull origin develop
   git checkout -b feature/<short-description>
   ```
2. Commit your changes and open a pull request into `develop`.
3. Once `develop` is stable and tested, open a pull request from `develop` into `prod` to release.

## Getting started

```bash
git clone https://github.com/The-GenAI-Labs/motionile.git
cd motionile
git checkout develop
```

## Contributing

All commits must be signed so they show as **Verified** on GitHub.
See [GitHub's guide to signing commits](https://docs.github.com/en/authentication/managing-commit-signature-verification/signing-commits).
