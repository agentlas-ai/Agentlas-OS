{
  "schemaVersion": "1.0",
  "kind": "agentlas-local-credential-store",
  "projectName": "{{PROJECT_NAME}}",
  "projectRoot": ".",
  "readFirst": "Read this map before saying a credential is missing, and before any deploy, release, store, billing, auth, API or cloud work. Values live in the .env files and secret folders named below, in the local keychain, or in a machine-wide environment variable named AGENTLAS_PROJECT_<PROJECT>_<ENV_NAME>. Write env names and relative paths here, never values.",
  "envFiles": [".env", ".env.local"],
  "secretDirs": ["signing", "credentials"],
  "entries": []
}
