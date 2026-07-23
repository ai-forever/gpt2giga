"""Static shell completion for the stable Harness command boundary."""

from __future__ import annotations

from typing import Final


SHELLS: Final = ("bash", "zsh", "fish", "powershell")

_ROOT_COMMANDS = (
    "agent bootstrap chat completion config doctor eval harness init integration memory "
    "native open preset project provider run runtime schedule session state tui "
    "ui worker workflow codex claude gemini"
)

_SCRIPTS: Final = {
    "bash": f"""# giga completion for Bash
_giga_complete() {{
    local current="${{COMP_WORDS[COMP_CWORD]}}"
    if (( COMP_CWORD == 1 )); then
        COMPREPLY=( $(compgen -W "{_ROOT_COMMANDS}" -- "$current") )
    else
        COMPREPLY=()
    fi
}}
complete -o default -F _giga_complete giga gpt2giga-harness
""",
    "zsh": f"""#compdef giga gpt2giga-harness
_giga() {{
  if (( CURRENT == 2 )); then
    compadd -- {_ROOT_COMMANDS}
  else
    _default
  fi
}}
compdef _giga giga gpt2giga-harness
""",
    "fish": """# giga completion for Fish
complete -c giga -f -n '__fish_use_subcommand' -a 'agent bootstrap chat completion config doctor eval harness init integration memory native open preset project provider run runtime schedule session state tui ui worker workflow codex claude gemini'
complete -c gpt2giga-harness -w giga
""",
    "powershell": f"""# giga completion for PowerShell
Register-ArgumentCompleter -Native -CommandName giga,gpt2giga-harness -ScriptBlock {{
    param($wordToComplete, $commandAst, $cursorPosition)
    if ($commandAst.CommandElements.Count -eq 2) {{
        '{_ROOT_COMMANDS}'.Split(' ') |
            Where-Object {{ $_ -like "$wordToComplete*" }} |
            ForEach-Object {{ [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_) }}
    }}
}}
""",
}


def render_completion(shell: str) -> str:
    """Render completion without parsing or mirroring provider-owned suffixes."""
    try:
        return _SCRIPTS[shell]
    except KeyError as exc:  # pragma: no cover - argparse owns public validation.
        raise ValueError(f"Unsupported shell: {shell}") from exc
