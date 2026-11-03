"""Create-only standalone skill discovery with session-local Codex MCP flags.

The single user-skill alias is never replaced or removed. A different existing
generation, duplicate qualified skill identity, or ambiguous discovery root fails closed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re


def _codex_home(home):
    from .host_core import Conflict, _plain
    configured = Path(os.environ.get('CODEX_HOME', str(home / '.codex'))).expanduser()
    _plain(configured)
    if not configured.is_absolute() or not configured.resolve().is_relative_to(home):
        raise Conflict('codex_home_outside_owner_home')
    return configured.resolve()


def _configuration_roots(home, skill_targets=None):
    from .host_core import Conflict, _plain, _read
    configured = _codex_home(home)
    roots = [home / '.agents/skills', home / '.codex/skills', configured / 'skills', configured / 'plugins/cache']
    config = configured / 'config.toml'
    if config.exists():
        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib
            except ImportError:
                raise Conflict('codex_configuration_parser_unavailable')
        parsed = tomllib.loads(_read(config).decode('utf-8'))
        for key in ('mcp_servers','features','skills','marketplaces','plugins'):
            if not isinstance(parsed.get(key,{}),dict):raise Conflict('codex_configuration_schema_unverified')
        for identity,value in parsed.get('plugins',{}).items():
            if identity.split('@',1)[0]=='agentlas-os-core' and (not isinstance(value,dict) or value.get('enabled') is not False):
                raise Conflict('codex_plugin_identity_collision')
        if 'agentlas_os' in parsed.get('mcp_servers', {}):
            raise Conflict('codex_mcp_name_collision')
        if parsed.get('features', {}).get('skills') is False:
            raise Conflict('codex_skills_disabled')
        rules=parsed.get('skills', {}).get('config', [])
        if not isinstance(rules,list):raise Conflict('codex_skill_configuration_unverified')
        targets=skill_targets or {}
        disabled=set()
        for item in rules:
            if not isinstance(item,dict) or type(item.get('enabled')) is not bool:
                raise Conflict('codex_skill_configuration_unverified')
            has_path=isinstance(item.get('path'),str)
            has_name=isinstance(item.get('name'),str)
            if has_path==has_name:raise Conflict('codex_skill_configuration_unverified')
            matches=set()
            if has_name:
                name=item['name'].strip()
                if name in targets:matches.add(name)
            else:
                path=Path(item['path']).expanduser()
                if not path.is_absolute():raise Conflict('codex_skill_configuration_unverified')
                resolved=path.resolve()
                for name,target in targets.items():
                    alias_path=configured/'skills/agentlas-os-core'/target.parent.name/'SKILL.md'
                    if resolved==target.resolve() or path==alias_path:matches.add(name)
                if item['enabled']:roots.append(path.parent if path.name=='SKILL.md' else path)
            # Native Codex applies selectors in order; a later enable restores
            # the matched identity, even after an earlier path-based disable.
            if item['enabled']:disabled.difference_update(matches)
            else:disabled.update(matches)
        if disabled:raise Conflict('codex_core_skill_explicitly_disabled:'+sorted(disabled)[0])

        for item in parsed.get('marketplaces', {}).values():
            if not isinstance(item, dict):
                raise Conflict('codex_marketplace_schema_unverified')
            if item.get('source_type') == 'local' and isinstance(item.get('source'), str):
                roots.append(Path(item['source']).expanduser())
            elif item.get('source_type') not in ('git', 'remote'):
                raise Conflict('codex_marketplace_source_unverified')
    cwd = Path.cwd().resolve()
    ancestors = [cwd, *cwd.parents]
    repository = next((parent for parent in ancestors if (parent / '.git').exists()), None)
    project_roots = ancestors[:ancestors.index(repository) + 1] if repository else [cwd]
    roots.extend(parent / '.agents/skills' for parent in project_roots)
    return list(dict.fromkeys(roots))


RESERVED_SKILLS = {'hep-search','hep-call','hep-goal','agentlas-search','agentlas-call','agentlas-goal','session-agent-builder'}


def _check_name_collisions(home, alias, names, target):
    from .host_core import Conflict
    expected={'agentlas-os-core:'+name for name in names}
    visited=set()
    count=0
    for root in _configuration_roots(home, {'agentlas-os-core:'+name:target/name/'SKILL.md' for name in names}):
        if not root.exists():
            continue
        for directory,folders,files in os.walk(root,followlinks=True):
            directory=Path(directory)
            try:resolved=directory.resolve(strict=True)
            except (OSError,RuntimeError):
                folders[:]=[];continue
            if resolved in visited:
                folders[:]=[];continue
            visited.add(resolved)
            count+=1
            if count>20000:raise Conflict('codex_skill_inventory_too_large')
            # Reading other links is safe. Only our create-only publication
            # uses no-follow directory descriptors; scans never rewrite links.
            for name in list(folders):
                if directory/name==alias:folders.remove(name)
            if 'SKILL.md' not in files:continue
            path=directory/'SKILL.md'
            try:
                actual=path.resolve(strict=True)
                if actual.is_relative_to(target):continue
                with path.open('r',encoding='utf-8') as stream:prefix=stream.read(8192)
            except (OSError,RuntimeError,UnicodeError):
                continue
            match=re.search(r'^name:\s*[\"\']?([^\"\'\r\n]+)',prefix,re.MULTILINE)
            name=match.group(1).strip() if match else directory.name
            identities={name}
            # Native Codex qualifies a skill under a plugin manifest. Check
            # that identity, not an unrelated legacy skill's bare spelling.
            for parent in (actual.parent,*actual.parent.parents):
                found=False
                for rel in ('.codex-plugin/plugin.json','.claude-plugin/plugin.json'):
                    manifest=parent/rel
                    if manifest.is_file():
                        try:document=json.loads(manifest.read_text(encoding='utf-8'))
                        except (OSError,ValueError):raise Conflict('codex_skill_namespace_unverified')
                        namespace=document.get('name') if isinstance(document,dict) else None
                        if not isinstance(namespace,str):raise Conflict('codex_skill_namespace_unverified')
                        identities.add(namespace+':'+name);found=True
                if found:break
            collision=identities&expected
            if collision:raise Conflict('codex_skill_identity_collision:'+sorted(collision)[0])


def _alias(home, target, *, create):
    from .host_core import Conflict, _plain
    parent = _codex_home(home) / 'skills'
    alias = parent / 'agentlas-os-core'
    _plain(parent)
    if alias.is_symlink():
        if (os.name != 'nt' and os.readlink(alias) != str(target)) or alias.resolve(strict=True) != target:
            previous=alias.resolve(strict=True)
            if previous.name=='skills' and previous.parent.name=='plugin' and previous.parent.parent.parent==target.parent.parent.parent:
                from .host_core import _verify_generation
                record=_verify_generation(previous.parent.parent)
                if record.get('host')=='codex' and record.get('kind')=='core':
                    raise Conflict('codex_skill_alias_outdated')
            raise Conflict('codex_skill_alias_conflict')
        return alias
    if alias.exists():
        raise Conflict('codex_skill_alias_conflict')
    if not create:
        raise Conflict('codex_skill_alias_unprepared')
    if os.name == 'nt':
        from .windows_skill_alias import publish
        publish(alias, target)
        return alias
    if not hasattr(os, 'O_NOFOLLOW') or os.symlink not in os.supports_dir_fd:
        raise Conflict('codex_atomic_skill_alias_unsupported')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(home, flags)
    try:
        for part in parent.relative_to(home).parts:
            try:
                os.mkdir(part, mode=0o700, dir_fd=descriptor)
            except FileExistsError:
                pass
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        try:
            os.symlink(str(target), 'agentlas-os-core', target_is_directory=True, dir_fd=descriptor)
        except FileExistsError:
            raise Conflict('codex_skill_alias_concurrent_collision')
        # Check the same open directory and the published user-visible path.
        if os.readlink('agentlas-os-core', dir_fd=descriptor) != str(target):
            raise Conflict('codex_skill_alias_changed')
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _plain(parent)
    if not alias.is_symlink() or alias.resolve(strict=True) != target:
        raise Conflict('codex_skill_alias_changed')
    return alias


def command(root, home, plugin, *, prepare=False):
    from .host_core import Conflict, _read, _verify_generation
    plugin = Path(plugin)
    record = _verify_generation(plugin.parent)
    if record.get('runtime') != str(root) or record.get('host') != 'codex' or record.get('kind') != 'core':
        raise Conflict('codex_skill_generation_identity_changed')
    alias = _codex_home(home) / 'skills/agentlas-os-core'
    from .host_core import SKILLS
    names=set(SKILLS) | RESERVED_SKILLS
    published_names=set()
    for relative in record['files']:
        if relative.startswith('skills/') and relative.endswith('/SKILL.md'):
            text=_read(plugin/relative).decode('utf-8')
            match=re.search(r'^name:\s*[\"\']?([^\"\'\r\n]+)',text,re.MULTILINE)
            if not match or not re.fullmatch(r'[A-Za-z0-9_-]+',match.group(1).strip()):raise Conflict('codex_generated_skill_name_unverified')
            names.add(match.group(1).strip());published_names.add(match.group(1).strip())
    _check_name_collisions(home, alias, names, plugin/'skills')
    alias = _alias(home, plugin / 'skills', create=prepare)
    _check_name_collisions(home, alias, names, plugin/'skills')
    server = json.loads(_read(plugin / '.mcp.json'))['mcpServers']['hephaestus-network']
    if set(server) != {'command', 'args'} or not isinstance(server['command'], str) or not isinstance(server['args'], list):
        raise Conflict('codex_mcp_launch_vector_unverified')
    vector = ['codex', '-c', 'mcp_servers.agentlas_os.command=' + json.dumps(server['command']),
              '-c', 'mcp_servers.agentlas_os.args=' + json.dumps(server['args'])]
    return vector, {'alias': str(alias), 'target': str(plugin / 'skills'), 'publication': 'create_only',
                    'updatePolicy': 'preserve_existing_alias_and_report_conflict', 'slashAliasesObserved': False,
                    'qualifiedSkillNames':sorted('agentlas-os-core:'+name for name in published_names),
                    'legacyBareNamesMayCoexist':True,'unqualifiedSkillSelectionVerified':False}
