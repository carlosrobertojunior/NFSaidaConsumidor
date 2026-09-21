import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .acbr import AcbrClient
from .batch import Batch
from .certificate_picker import CertificatePicker
from .certificates import list_certificates
from .domain import AppError, Month
from .sefaz import SefazMG


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("NFC-e MG • Arquivos mensais")
        self.geometry("1000x760")
        self.minsize(850, 680)
        self.certificates = []
        self.messages = queue.Queue()
        self.stop = threading.Event()
        self.busy = False
        self.last_zip = None
        self.picker = None
        self.configure(background="#f1f5f9")
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#f1f5f9")
        style.configure("TLabel", background="#f1f5f9", foreground="#172b4d", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10), padding=7)
        panel = ttk.Frame(self, padding=24)
        panel.pack(fill="both", expand=True)
        panel.columnconfigure(1, weight=1)
        ttk.Label(panel, text="NFC-e de saída · Minas Gerais", font=("Segoe UI", 21, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 6)
        )
        ttk.Label(panel, text="Selecione o certificado, a origem dos XMLs e a competência.").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(0, 16)
        )
        self.cert = tk.StringVar()
        ttk.Label(panel, text="Certificado Windows").grid(row=2, column=0, sticky="w")
        self.cert_combo = ttk.Combobox(panel, textvariable=self.cert, state="readonly")
        self.cert_combo.grid(row=2, column=1, sticky="ew", padx=10, pady=6)
        self.cert_combo.bind("<<ComboboxSelected>>", self.select_certificate)
        self.refresh_button = ttk.Button(panel, text="Atualizar", command=self.open_picker)
        self.refresh_button.grid(row=2, column=2)
        self.cnpj = tk.StringVar()
        self.row(panel, 3, "CNPJ do certificado", self.cnpj, readonly=True)
        self.month = tk.StringVar(value=str(Month.previous()))
        self.row(panel, 4, "Competência (AAAA-MM)", self.month)
        self.environment = tk.StringVar(value="producao")
        self.combo(panel, 5, "Ambiente fiscal", self.environment, ["producao", "homologacao"])
        self.source = tk.StringVar(value="Pasta do emissor/ERP")
        self.combo(panel, 6, "Origem dos XMLs", self.source, ["Pasta do emissor/ERP", "ACBr API"])
        self.folder = tk.StringVar()
        self.row(panel, 7, "Pasta de origem", self.folder)
        ttk.Button(panel, text="Escolher", command=lambda: self.choose_folder(self.folder)).grid(
            row=7, column=2
        )
        output_root = (
            Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "NFCeMG"
            if getattr(sys, "frozen", False)
            else Path.cwd()
        )
        self.output = tk.StringVar(value=str(output_root / "exports"))
        self.row(panel, 8, "Pasta de saída", self.output)
        ttk.Button(panel, text="Escolher", command=lambda: self.choose_folder(self.output)).grid(
            row=8, column=2
        )
        self.api_environment = tk.StringVar(value="producao")
        self.combo(panel, 9, "Servidor ACBr", self.api_environment, ["producao", "sandbox"])
        self.client_id = tk.StringVar(value=os.environ.get("ACBR_CLIENT_ID", ""))
        self.secret = tk.StringVar(value=os.environ.get("ACBR_CLIENT_SECRET", ""))
        self.row(panel, 10, "ACBr Client ID", self.client_id)
        self.row(panel, 11, "ACBr Client Secret", self.secret, secret=True)
        ttk.Label(
            panel,
            text="ACBr: baixa notas disponíveis na sua conta; exige credenciais próprias.\n"
            "SEFAZ MG: consulta status/protocolo com o certificado; não oferece lote mensal nesta integração.\n"
            "A chave privada permanece no Windows. Credenciais ACBr ficam somente na memória.",
            wraplength=890,
        ).grid(row=12, column=0, columnspan=3, sticky="w", pady=12)
        actions = ttk.Frame(panel)
        actions.grid(row=13, column=0, columnspan=3, sticky="ew")
        self.run_button = ttk.Button(actions, text="Gerar lote mensal", command=self.export)
        self.run_button.pack(side="left")
        self.status_button = ttk.Button(actions, text="Status SEFAZ MG", command=self.status_sefaz)
        self.status_button.pack(side="left", padx=6)
        self.consult_button = ttk.Button(actions, text="Consultar chave", command=self.consult)
        self.consult_button.pack(side="left")
        ttk.Button(actions, text="Interromper", command=self.stop.set).pack(side="right")
        self.log = tk.Text(panel, height=8, state="disabled", font=("Consolas", 9), wrap="word")
        self.log.grid(row=14, column=0, columnspan=3, sticky="nsew", pady=(12, 0))
        panel.rowconfigure(14, weight=1)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(100, self.poll)
        self.after(200, self.open_picker)

    def row(self, panel, index, label, variable, readonly=False, secret=False):
        ttk.Label(panel, text=label).grid(row=index, column=0, sticky="w")
        ttk.Entry(
            panel,
            textvariable=variable,
            state="readonly" if readonly else "normal",
            show="•" if secret else "",
        ).grid(row=index, column=1, sticky="ew", padx=10, pady=5)

    def combo(self, panel, index, label, variable, values):
        ttk.Label(panel, text=label).grid(row=index, column=0, sticky="w")
        ttk.Combobox(panel, textvariable=variable, values=values, state="readonly").grid(
            row=index, column=1, sticky="ew", padx=10, pady=5
        )

    def choose_folder(self, variable):
        path = filedialog.askdirectory(parent=self)
        if path:
            variable.set(path)

    def selected(self):
        index = self.cert_combo.current()
        if index < 0 or index >= len(self.certificates):
            raise AppError("Selecione um certificado e-CNPJ instalado no Windows.")
        cert = self.certificates[index]
        cert.check()
        return cert

    def select_certificate(self, _event=None):
        index = self.cert_combo.current()
        self.cnpj.set(self.certificates[index].cnpj if index >= 0 else "")

    def write(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def launch(self, function):
        if self.busy:
            return
        self.busy = True
        self.stop.clear()
        for button in (self.run_button, self.status_button, self.consult_button, self.refresh_button):
            button.configure(state="disabled")

        def work():
            try:
                self.messages.put(("result", function()))
            except AppError as exc:
                self.messages.put(("error", str(exc)))
            except Exception:  # noqa: BLE001 -- GUI boundary; hides sensitive transport details.
                self.messages.put(
                    ("error", "Falha inesperada. Verifique acesso às pastas, dependências e conexão.")
                )
            finally:
                self.messages.put(("done", None))

        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, data = self.messages.get_nowait()
                if kind == "log":
                    self.write(data)
                elif kind == "error":
                    self.write("Erro: " + data)
                    messagebox.showerror("Não foi possível concluir", data, parent=self.picker or self)
                elif kind == "done":
                    self.busy = False
                    if self.picker is not None:
                        self.picker.set_loading(False)
                    for button in (
                        self.run_button,
                        self.status_button,
                        self.consult_button,
                        self.refresh_button,
                    ):
                        button.configure(state="normal")
                elif kind == "result":
                    if isinstance(data, list):
                        self.certificates = data
                        if self.picker is not None:
                            self.picker.populate(data)
                        self.cert_combo["values"] = [cert.label for cert in data]
                        self.cert.set("")
                        self.cnpj.set("")
                        self.write(f"{len(data)} certificados e-CNPJ encontrados. Selecione um para começar.")
                    elif isinstance(data, dict) and "arquivo_zip" in data:
                        self.last_zip = data["arquivo_zip"]
                        text = (
                            f"Lote {data['resultado']}: {data['xmls']} XMLs, {len(data['erros'])} pendências.\n"
                            f"ZIP: {self.last_zip}\nRelatório: {data['relatorio']}\n"
                            "O lote reflete apenas a origem selecionada."
                        )
                        self.write(text)
                        messagebox.showinfo("Resultado do lote", text, parent=self)
                    else:
                        self.write(f"SEFAZ MG: {data['codigo']} — {data['motivo']}")
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def open_picker(self):
        if self.busy:
            return
        if self.picker is None:
            self.picker = CertificatePicker(self)
        else:
            self.picker.lift()
        self.refresh()

    def refresh(self):
        if self.busy:
            return
        if self.picker is not None:
            self.picker.set_loading(True)
        self.launch(list_certificates)

    def export(self):
        try:
            cert = self.selected()
            month = Month.parse(self.month.get().strip())
            environment, source = self.environment.get(), self.source.get()
            api_environment = self.api_environment.get()
            if source == "ACBr API" and api_environment == "sandbox" and environment == "producao":
                raise AppError("Servidor sandbox exige ambiente fiscal homologacao.")
            folder, output = self.folder.get().strip(), self.output.get().strip()
            if not output:
                raise AppError("Informe uma pasta de saída.")
            if source != "ACBr API" and (not folder or not Path(folder).is_dir()):
                raise AppError("Informe a pasta onde o emissor/ERP grava os XMLs.")
            client_id, secret = self.client_id.get().strip(), self.secret.get()
            if source == "ACBr API" and (not client_id or not secret):
                raise AppError("Informe as credenciais ACBr.")
        except AppError as exc:
            messagebox.showerror("Confira os dados", str(exc), parent=self)
            return
        self.write(f"Iniciando {source} · CNPJ {cert.cnpj} · {month} · {environment}")

        def work():
            cert.check()
            batch = Batch(
                Path(output),
                cert.cnpj,
                month,
                environment,
                stop=self.stop,
                progress=lambda text: self.messages.put(("log", text)),
            )
            if source == "ACBr API":
                client = AcbrClient(client_id, secret, api_environment)
                try:
                    return batch.from_acbr(client)
                finally:
                    client.close()
            return batch.from_folder(Path(folder))

        self.launch(work)

    def status_sefaz(self):
        try:
            sefaz = SefazMG(self.selected(), self.environment.get())
        except AppError as exc:
            messagebox.showerror("Certificado", str(exc), parent=self)
            return
        self.write("Consultando a SEFAZ MG com o certificado selecionado…")
        self.launch(sefaz.status)

    def consult(self):
        try:
            sefaz = SefazMG(self.selected(), self.environment.get())
        except AppError as exc:
            messagebox.showerror("Certificado", str(exc), parent=self)
            return
        key = simpledialog.askstring("Consulta por chave", "Chave NFC-e MG (44 dígitos):", parent=self)
        if key:
            self.launch(lambda: sefaz.consult(key.strip()))

    def close(self):
        if self.busy:
            self.stop.set()
            self.write("Interrupção solicitada. Aguarde a requisição atual terminar e feche novamente.")
            return
        self.secret.set("")
        self.destroy()


def run():
    App().mainloop()
