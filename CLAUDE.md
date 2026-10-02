# CLAUDE.md

@AGENTS.md

## Notas para Claude Code

- **Supabase por MCP** (`.mcp.json`): úsalo para inspeccionar la base (`list_tables`,
  `execute_sql` de solo lectura, `get_advisors`). Los cambios de esquema van como archivo nuevo en
  `supabase/migrations/` y se aplican con `npx supabase db push` o `psql`; no los apliques solo por
  MCP, porque el repo tiene que poder recrear la base.
- **Skills de Supabase** (`skills-lock.json`): `supabase` y `supabase-postgres-best-practices`.
  Consúltalas antes de escribir una migración o una política de RLS.
- **Documentación de librerías**: LlamaIndex, FlagEmbedding, Docling, Chroma y la API de Ollama
  cambian seguido; revisa la documentación vigente (Context7) antes de usar una API que no aparezca
  ya en el código. Las versiones fijadas están en `backend/requirements.txt` e
  `ingesta/requirements.txt`.
- **Comandos lentos**: cargar bge-m3 y el reranker tarda varios segundos; `ingesta.extraer` ~2 min;
  los scripts de `eval/` varios minutos. Córrelos en segundo plano y no los repitas solo para
  verificar algo que ya mostró la salida.
- `.claude/` está en `.gitignore` (incluye `worktrees/`): nada de ahí se versiona.
