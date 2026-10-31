"""Escuta por voz local (Etapa 2): microfone → palavra de ativação → fim de fala → Whisper → fala local.

Roda num processo separado da API (python -m jarvis.voz) e só com JARVIS_VOZ_LOCAL=1. Depende do extra [voz]:
os imports pesados (numpy, onnxruntime, sounddevice, openwakeword) ficam dentro dos módulos que os usam, para a
API continuar subindo sem eles.
"""
