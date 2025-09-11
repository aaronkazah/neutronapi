# GitHub Workflows

This directory contains the CI/CD workflows for NeutronAPI.

## test.yml

The main test workflow that runs on every push and pull request. It includes:

### Jobs:

1. **lint** - Code quality checks using ruff
2. **test-sqlite** - Tests using SQLite (default configuration)
3. **test-postgresql** - Tests using PostgreSQL with Docker service
4. **test-matrix** - Matrix testing across Python 3.11/3.12 and both SQLite/PostgreSQL

### Database Testing:

- **SQLite**: Uses NeutronAPI's default in-memory SQLite configuration
- **PostgreSQL**: Uses `DATABASE_PROVIDER=asyncpg` environment variable to enable PostgreSQL testing with a Docker PostgreSQL 15 service

### Status Badge:

```markdown
![Tests](https://github.com/YOUR_USERNAME/neutronapi/workflows/Tests/badge.svg)
```

Replace `YOUR_USERNAME` with your GitHub username.