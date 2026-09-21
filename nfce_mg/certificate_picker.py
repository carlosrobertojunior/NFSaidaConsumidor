"""Tela inicial para escolha explícita de um certificado instalado."""

import tkinter as tk
from tkinter import messagebox, ttk

from .domain import AppError


class CertificatePicker(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("NFC-e MG — Selecionar certificado")
        self.geometry("1000x440")
        self.minsize(820, 400)
        self.transient(app)
        self.configure(background="#f1f5f9")
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        panel = ttk.Frame(self, padding=24)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="Escolha o certificado da empresa", font=("Segoe UI", 20, "bold")).pack(
            anchor="w"
        )
        ttk.Label(
            panel, text="O CNPJ selecionado será usado para organizar seus lotes de NFC-e.", wraplength=900
        ).pack(anchor="w", pady=(6, 18))
        table_frame = ttk.Frame(panel)
        table_frame.pack(fill="both", expand=True)
        self.table = ttk.Treeview(
            table_frame,
            columns=("empresa", "cnpj", "validade", "situacao"),
            show="headings",
            selectmode="browse",
            height=6,
        )
        for name, text, width in (
            ("empresa", "Empresa / certificado", 410),
            ("cnpj", "CNPJ", 145),
            ("validade", "Válido até", 110),
            ("situacao", "Situação", 120),
        ):
            self.table.heading(name, text=text)
            self.table.column(name, width=width, minwidth=80)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.table.pack(side="left", fill="both", expand=True)
        self.table.bind("<<TreeviewSelect>>", self.selection_changed)
        self.table.bind("<Double-1>", self.confirm)
        self.bind("<Return>", self.confirm)
        self.detail = tk.StringVar(value="Consultando os certificados instalados no Windows…")
        ttk.Label(panel, textvariable=self.detail, wraplength=930).pack(anchor="w", pady=(10, 6))
        ttk.Label(
            panel,
            text="A chave privada permanece no Windows. Nenhum certificado é enviado nesta etapa.",
            wraplength=930,
        ).pack(anchor="w")
        actions = ttk.Frame(panel)
        actions.pack(fill="x", pady=(16, 0))
        self.refresh_button = ttk.Button(actions, text="Atualizar lista", command=app.refresh)
        self.refresh_button.pack(side="left")
        ttk.Button(actions, text="Fechar", command=self.cancel).pack(side="right")
        self.continue_button = ttk.Button(
            actions, text="Usar certificado", command=self.confirm, state="disabled"
        )
        self.continue_button.pack(side="right", padx=(0, 8))
        self.grab_set()
        self.table.focus_set()

    def set_loading(self, loading):
        self.refresh_button.configure(state="disabled" if loading else "normal")
        if loading:
            self.detail.set("Consultando os certificados instalados no Windows…")
            self.continue_button.configure(state="disabled")

    def populate(self, certificates):
        self.table.delete(*self.table.get_children())
        for index, cert in enumerate(certificates):
            try:
                cert.check()
                status = "Válido"
            except AppError:
                status = "Fora da validade"
            self.table.insert(
                "",
                "end",
                iid=str(index),
                values=(cert.subject, cert.cnpj, cert.valid_to.strftime("%d/%m/%Y"), status),
            )
        self.continue_button.configure(state="disabled")
        self.detail.set(
            f"{len(certificates)} certificado(s) encontrado(s). Selecione a empresa para continuar."
            if certificates
            else "Nenhum e-CNPJ encontrado. Instale o A1 ou conecte o A3 com seu driver e atualize a lista."
        )

    def selection_changed(self, _event=None):
        selected = self.table.selection()
        if not selected:
            return
        cert = self.app.certificates[int(selected[0])]
        self.detail.set(f"Repositório: {cert.store} | Identificador: {cert.thumbprint}")
        try:
            cert.check()
            self.continue_button.configure(state="normal")
        except AppError:
            self.continue_button.configure(state="disabled")

    def confirm(self, _event=None):
        if self.app.busy:
            return
        selected = self.table.selection()
        if not selected:
            return
        index = int(selected[0])
        try:
            self.app.certificates[index].check()
        except AppError as exc:
            messagebox.showerror("Certificado indisponível", str(exc), parent=self)
            return
        self.app.cert_combo.current(index)
        self.app.select_certificate()
        self.grab_release()
        self.app.picker = None
        self.destroy()
        self.app.lift()
        self.app.focus_force()

    def cancel(self):
        self.grab_release()
        self.app.picker = None
        self.destroy()
