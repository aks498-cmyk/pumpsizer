# Security Policy

## Scope

`pumpsizer` is an offline engineering-calculation library and CLI. It reads
project files, pipe/pump data tables and EPANET `.inp` files you point it at,
and (optionally) shells out to the bundled EPANET solver via `epyt`. It opens
no network connections and stores no credentials.

The realistic concerns are therefore:

- a crafted **project YAML**, **catalogue file** or **`.inp`** causing
  unsafe behaviour (path traversal on write, code execution, resource
  exhaustion) rather than just a clean error;
- a dependency (`numpy`, `scipy`, `pyyaml`, `matplotlib`, `openpyxl`, `epyt`)
  vulnerability that reaches users through this package.

Dependency advisories are tracked automatically (Dependabot alerts + security
updates are enabled on the repository).

## Supported versions

The project is pre-1.0. Only the latest `master` is supported; fixes are not
back-ported.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

Use GitHub's private reporting: **Security → Report a vulnerability** on
<https://github.com/aks498-cmyk/pumpsizer/security/advisories/new>, or email
the maintainer (aks498@gmail.com) with:

- affected version / commit,
- a minimal file or command that triggers it,
- the impact you see.

Expect an acknowledgement within about a week. Coordinated disclosure is
appreciated; credit is given in the fix commit unless you prefer otherwise.
