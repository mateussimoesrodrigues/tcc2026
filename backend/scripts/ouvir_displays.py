"""Ouvinte MQTT dos displays de prateleira -- ferramenta de diagnostico.

Faz o papel do `mosquitto_sub`, mas usando o `paho-mqtt` que ja esta no
requirements do projeto: nao precisa instalar cliente MQTT nenhum na
maquina (util no Windows, onde os utilitarios do mosquitto dao trabalho
pra instalar).

Serve pra responder uma pergunta so, e responder rapido: **o backend esta
publicando?** Se a mensagem aparece aqui quando voce aprova uma promocao
no painel, o lado do servidor esta certo e qualquer problema que sobrar e
do firmware/hardware.

Le a configuracao do mesmo `.env` do backend (MQTT_HOST, MQTT_PORT, etc.),
entao se o app publica, este script escuta -- sem risco de testar contra
um broker diferente do que a aplicacao usa.

Uso:
    cd backend
    ./venv/Scripts/python.exe -m scripts.ouvir_displays

    # sobrescrevendo o .env (ex.: broker local pra teste rapido)
    ./venv/Scripts/python.exe -m scripts.ouvir_displays \
        --host localhost --porta 1883 --sem-tls
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from app.core.config import get_settings


def _formatar(payload: str) -> str:
    """Mostra o JSON de um jeito legivel, destacando o que a etiqueta
    desenha. Se nao for JSON valido, mostra cru -- que ja e a informacao
    util nesse caso."""
    try:
        dados = json.loads(payload)
    except json.JSONDecodeError:
        return f"    (payload nao e JSON) {payload}"

    if not dados.get("tem_produto"):
        return f"    display #{dados.get('display_id')} sem produto vinculado"

    linhas = [
        f"    display  : #{dados.get('display_id')} ({dados.get('display_nome')})",
        f"    produto  : {dados.get('produto_nome')} {dados.get('marca') or ''}".rstrip(),
    ]
    if dados.get("promocao_ativa"):
        linhas.append(
            f"    preco    : de R$ {dados.get('preco_normal')} "
            f"por R$ {dados.get('preco_vigente')}  "
            f"(-{dados.get('percentual_desconto')}%)   << EM PROMOCAO"
        )
    else:
        linhas.append(f"    preco    : R$ {dados.get('preco_vigente')}  (sem promocao)")
    linhas.append(f"    gerado em: {dados.get('gerado_em')}")
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default=settings.mqtt_host)
    parser.add_argument("--porta", type=int, default=settings.mqtt_port)
    parser.add_argument("--usuario", default=settings.mqtt_username)
    parser.add_argument("--senha", default=settings.mqtt_password)
    parser.add_argument("--prefixo", default=settings.mqtt_topic_prefix)
    parser.add_argument("--sem-tls", action="store_true", help="broker local sem TLS (porta 1883)")
    args = parser.parse_args(argv)

    if not args.host:
        print("ERRO: nenhum broker configurado.")
        print("  Preencha MQTT_HOST no backend/.env, ou passe --host aqui.")
        return 2

    usar_tls = settings.mqtt_use_tls and not args.sem_tls
    topico = f"{args.prefixo}/#"

    from paho.mqtt import client as mqtt

    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ouvinte-diagnostico")
    if args.usuario:
        cliente.username_pw_set(args.usuario, args.senha)
    if usar_tls:
        cliente.tls_set()

    def ao_conectar(client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            print(f"\nFALHA ao conectar: {reason_code}")
            print("  5 / 'Not authorized' -> usuario ou senha do broker errados")
            print("  Verifique tambem host, porta e se o broker exige TLS.")
            return
        print(f"Conectado em {args.host}:{args.porta}" + (" (TLS)" if usar_tls else ""))
        client.subscribe(topico, qos=1)
        print(f"Assinando  {topico}")
        print()
        print("Aguardando... aprove uma promocao no painel para ver a mensagem aqui.")
        print("(Ctrl+C para sair)")
        print("-" * 70)

    def ao_receber(client, userdata, msg):
        agora = datetime.now().strftime("%H:%M:%S")
        retida = "  [retida]" if msg.retain else ""
        print(f"\n[{agora}] {msg.topic}{retida}")
        print(_formatar(msg.payload.decode("utf-8", errors="replace")))

    cliente.on_connect = ao_conectar
    cliente.on_message = ao_receber

    print(f"Conectando em {args.host}:{args.porta}...")
    try:
        cliente.connect(args.host, args.porta, keepalive=60)
    except Exception as e:  # noqa: BLE001 -- e um script de diagnostico
        print(f"\nERRO ao conectar: {e}")
        print("  Confira MQTT_HOST/MQTT_PORT no .env e se a maquina alcanca o broker.")
        return 1

    try:
        cliente.loop_forever()
    except KeyboardInterrupt:
        print("\nEncerrando.")
        cliente.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
