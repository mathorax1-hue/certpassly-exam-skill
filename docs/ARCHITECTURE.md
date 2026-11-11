# Architecture and connection boundaries

```
                  PUBLIC: certpassly-exam-skill
             modules, tests, knowledge, CLI, MCP
                       |              |
                       v              v
               PUBLIC: exam       upstream pin
               processor          (external)
                       |              |
                       +-------+------+
                               v
                   PRIVATE: raw-exam
             source PDFs, visual keys, evidence
                               |
                         release gate
                               v
                 PRIVATE: ready-exams
                independent approved drafts
```

1. **GitHub connector** is the operator's external control-plane integration. The skill does not embed or print its token.
2. **Core CLI** runs in a local/private checkout and stores state in SQLite. It is designed to resume trusted workflow stages.
3. **Upstream adapter** calls the existing 15-stage runner from a separate SHA-verified checkout; it does not reproduce external source code.
4. **Read-only MCP** offers diagnostic data only. No arbitrary shell, writes to GitHub, site import, or package promotion.
5. **Production release** belongs to a separately protected private repository workflow. No self-attested JSON alone can grant authority.
6. **Optional Supabase** can later store metadata and review queues. It requires a project, scoped credentials, RLS and database migrations. No Supabase project is currently configured by this repository.
7. **Large artifacts** belong in private storage with hashes and retention rules; SQLite stores local checkpoints and hashes, not public exam media.

The first version deliberately keeps the core dependency-free to lower maintenance costs and allow synthetic CI without private exam data.
