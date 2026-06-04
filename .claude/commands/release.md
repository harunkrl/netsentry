Prepare a new release:
1. Read current version from pyproject.toml
2. Ask the user what version to bump to (patch/minor/major or specific)
3. Update version in pyproject.toml and shared/constants.py (APP_VERSION)
4. Update CHANGELOG.md with the new version entry — list notable commits since last tag
5. Commit the version bump
6. Create a git tag with the version
