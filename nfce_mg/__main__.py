import argparse
import json
import os
from pathlib import Path

from .acbr import AcbrClient
from .batch import Batch
from .certificates import list_certificates
from .domain import AppError, Month


def main():
    parser = argparse.ArgumentParser(description="NFC-e MG: arquivos mensais da ACBr ou do emissor.")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("gui", help="Abrir a interface Windows (padrão)")
    commands.add_parser("certificados", help="Listar e-CNPJs instalados no Windows")
    export = commands.add_parser("exportar", help="Lote mensal; permite agendamento externo")
    export.add_argument("--certificado", required=True, help="Thumbprint exato do certificado Windows")
    export.add_argument("--store", choices=["CurrentUser", "LocalMachine"], default="CurrentUser")
    export.add_argument("--mes", default=str(Month.previous()), help="AAAA-MM; padrão: mês anterior")
    export.add_argument("--origem", choices=["acbr", "pasta"], required=True)
    export.add_argument("--pasta", type=Path)
    export.add_argument("--saida", type=Path, default=Path("exports"))
    export.add_argument("--ambiente", choices=["producao", "homologacao"], default="producao")
    export.add_argument("--api", choices=["producao", "sandbox"], default="producao")
    args = parser.parse_args()
    try:
        if args.command in (None, "gui"):
            from .gui import run

            run()
            return
        certificates = list_certificates()
        if args.command == "certificados":
            for certificate in certificates:
                print(certificate.label, "|", certificate.thumbprint)
            return
        matches = [
            c
            for c in certificates
            if c.thumbprint.upper() == args.certificado.replace(" ", "").upper() and c.store == args.store
        ]
        if len(matches) != 1:
            raise AppError("Certificado não encontrado no repositório indicado.")
        certificate = matches[0]
        certificate.check()
        if args.api == "sandbox" and args.ambiente == "producao" and args.origem == "acbr":
            raise AppError("Sandbox exige ambiente fiscal homologacao.")
        batch = Batch(args.saida, certificate.cnpj, Month.parse(args.mes), args.ambiente, progress=print)
        if args.origem == "pasta":
            if not args.pasta:
                raise AppError("Informe --pasta para importar XMLs do emissor.")
            result = batch.from_folder(args.pasta)
        else:
            client = AcbrClient(
                os.getenv("ACBR_CLIENT_ID", ""), os.getenv("ACBR_CLIENT_SECRET", ""), args.api
            )
            try:
                result = batch.from_acbr(client)
            finally:
                client.close()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(2 if result["resultado"] == "parcial" else 0)
    except AppError as exc:
        parser.exit(1, f"Erro: {exc}\n")


if __name__ == "__main__":
    main()
