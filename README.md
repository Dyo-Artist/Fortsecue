# Fortsecue
For Fortescue related diagrams and code

## Development

Run `./setup.sh` to install dependencies and run lint/tests. The script hashes
`requirements.txt` (and other dependency files) and caches the installed
packages under `.cache/`. When the hash hasn't changed, the install step is
skipped, speeding up repeated runs.
