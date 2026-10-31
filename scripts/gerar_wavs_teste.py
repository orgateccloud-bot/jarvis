"""Gera os WAVs sintéticos dos testes de voz com as vozes pt-BR do Windows (SAPI): nenhuma gravação de pessoa.

    .venv\\Scripts\\python scripts\\gerar_wavs_teste.py

Saída: tests/fixtures/voz/<nome>.wav, 16 kHz, mono, 16 bits (o formato do serviço de voz), e textos.json com o
texto de cada um (referência do acerto do Whisper). Silêncio e ruído não viram arquivo: os testes geram na hora.
"""

from __future__ import annotations

import base64
import json

# só o pwsh do sistema, com argumentos fixos e sem shell
import subprocess  # nosec B404
import sys
from pathlib import Path

DESTINO = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "voz"

# nome do arquivo → (voz SAPI, texto)
FRASES = {
    "jarvis_que_horas_daniel": ("Microsoft Daniel", "Jarvis, que horas são?"),
    "jarvis_que_horas_maria": ("Microsoft Maria", "Jarvis, que horas são?"),
    "jarvis_daniel": ("Microsoft Daniel", "Jarvis."),
    "ok_jarvis_daniel": ("Microsoft Daniel", "Ok, Jarvis."),
    "ok_jarvis_maria": ("Microsoft Maria", "Ok, Jarvis."),
    "ok_jarvis_que_horas_daniel": ("Microsoft Daniel", "Ok, Jarvis, que horas são?"),
    "hey_jarvis_maria": ("Microsoft Maria", "Hey, Jarvis."),
    # eco: o que o próprio JARVIS fala (sem a palavra de ativação) não pode disparar
    "eco_disco_daniel": ("Microsoft Daniel", "O disco C está com oitenta e dois por cento de uso, Senhor."),
    "eco_lembrete_daniel": ("Microsoft Daniel", "Lembrete criado para as quinze horas. Mais alguma coisa?"),
    "eco_custo_maria": ("Microsoft Maria", "O custo do mês está em quatorze dólares, abaixo do teto."),
}


def _ps(texto: str) -> str:
    return "'" + texto.replace("'", "''") + "'"


def script(destino: Path) -> str:
    linhas = [
        "$ErrorActionPreference = 'Stop'",  # voz ausente vira erro, não um WAV silencioso com a voz padrão
        "Add-Type -AssemblyName System.Speech",
        ("$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, "
         "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)"),
    ]
    for nome, (voz, texto) in FRASES.items():
        wav = destino / f"{nome}.wav"
        linhas += [
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer",
            f"$s.SelectVoice({_ps(voz)})",
            f"$s.SetOutputToWaveFile({_ps(str(wav))}, $fmt)",
            f"$s.Speak({_ps(texto)})",
            "$s.Dispose()",
        ]
    return "\n".join(linhas)


def main() -> int:
    DESTINO.mkdir(parents=True, exist_ok=True)
    # PowerShell 7 (pwsh): o System.Speech do Windows PowerShell 5.1 só enxerga as vozes "Desktop" do SAPI
    # (medido: só Maria Desktop e Zira); as vozes OneCore Daniel e Maria, as mesmas do HUD, só aparecem no pwsh.
    # -EncodedCommand (UTF-16LE em base64): acentos chegam intactos.
    cod = base64.b64encode(script(DESTINO).encode("utf-16-le")).decode("ascii")
    r = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-EncodedCommand", cod],  # nosec B603 B607
                       capture_output=True, text=True, check=False)
    if r.returncode != 0:
        print(r.stderr or r.stdout, file=sys.stderr)
        return 1
    for nome in FRASES:
        wav = DESTINO / f"{nome}.wav"
        print(f"{wav.name}  {wav.stat().st_size / 1024:.0f} KB")
    textos = {nome: texto for nome, (_voz, texto) in FRASES.items()}
    (DESTINO / "textos.json").write_text(json.dumps(textos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
