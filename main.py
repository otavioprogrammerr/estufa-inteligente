# app.py
import os
import json
import time
import threading
import random
import customtkinter as ctk
from tkinter import messagebox
from PIL import Image, ImageTk
import serial.tools.list_ports

# ----------------- Config -----------------
CTK_BG = "#0f2610"
CTK_CARD = "#12381f"
CTK_BTN = "#2e4632"
CTK_HOVER = "#3f5e3f"
CTK_TEXT = "#d4e2d4"

PASTA_IMAGENS = "plantas"     # pasta com frio.png, calor.png, seco.png, arseco.png, normal.png
ARQ_PAISES = "paises.json"
ARQ_PLANTAS = "plantas.json"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")

# ----------------- Helpers JSON -----------------
def carregar_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def salvar_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# ----------------- Arduino Simulado -----------------
class ArduinoSim:
    """Simula leituras de solo e um relé na porta 10"""
    def __init__(self):
        # valores 0..1023 simulados
        self.solo = [600, 600, 600]
        self.pino10 = False

    def ler_solo(self):
        # pequena oscilação natural
        self.solo = [max(0, min(1023, int(v + random.uniform(-5, 5)))) for v in self.solo]
        return self.solo

    def set_pino10(self, estado):
        self.pino10 = bool(estado)

# ----------------- Main App -----------------
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("🌿 GrowSim - Sistema Plantas (com DB de países)")
        self.geometry("900x620")
        self.configure(bg=CTK_BG)

        # estado global
        self.arduino_porta = None
        self.ar_sim = ArduinoSim()
        self.simular_sem_arduino = True

        # parâmetros de plantas (carregado de plantas.json)
        self.plantas_db = carregar_json(ARQ_PLANTAS) or []  # lista de dicts
        self.paises_db = carregar_json(ARQ_PAISES) or {}

        # valores dinâmicos (inicial neutro)
        self.temperatura = 25.0
        self.umidade_ar = 55.0
        self.meta_temp = 25.0
        self.meta_umid = 55.0

        # estados tamagotchi/manual
        self.ativo_aquecer = False
        self.ativo_resfriar = False
        self.ativo_umidificar = False
        self.ativo_irrigar = False

        # relay states (7,9,10,11) para evitar spam serial
        self.relay_states = {7: False, 9: False, 10: False, 11: False}

        # UI frames
        self.frame_porta = TelaPorta(self, self.conectar_arduino)
        self.frame_selecao = TelaSelecaoPlanta(self, self.ir_para_simulacao, self.ir_para_adicionar)
        self.frame_adicionar = TelaAdicionarPlanta(self, self.voltar_selecao, self.atualizar_plantas, self.paises_db)
        self.frame_simulacao = None  # criado ao confirmar planta
        self.frame_tamagotchi = None

        # coloca apenas a frame_porta visível inicialmente
        for f in (self.frame_porta, self.frame_selecao, self.frame_adicionar):
            f.place(relx=1, rely=0, relwidth=1, relheight=1)
        self.frame_porta.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.frame_atual = self.frame_porta

        # binds secretos Ctrl+F/C/S/N
        self.bind_all('<Control-Key-f>', lambda e: self.process_cmd("F"))
        self.bind_all('<Control-Key-F>', lambda e: self.process_cmd("F"))
        self.bind_all('<Control-Key-c>', lambda e: self.process_cmd("C"))
        self.bind_all('<Control-Key-C>', lambda e: self.process_cmd("C"))
        self.bind_all('<Control-Key-s>', lambda e: self.process_cmd("S"))
        self.bind_all('<Control-Key-S>', lambda e: self.process_cmd("S"))
        self.bind_all('<Control-Key-n>', lambda e: self.process_cmd("N"))
        self.bind_all('<Control-Key-N>', lambda e: self.process_cmd("N"))

        # start loop de simulação (thread)
        self.running = True
        threading.Thread(target=self.loop_simulacao, daemon=True).start()

    # ---------- navegação com slide ----------
    def slide_to(self, frame_from, frame_to, speed=0.03):
        frame_to.place(relx=1, rely=0, relwidth=1, relheight=1)
        def mover():
            relx = float(frame_to.place_info()['relx'])
            if relx > 0:
                nova = max(0, relx - speed)
                frame_to.place_configure(relx=nova)
                frame_from.place_configure(relx=nova - 1)
                self.after(12, mover)
            else:
                frame_from.place_forget()
                frame_to.place(relx=0, rely=0, relwidth=1, relheight=1)
                self.frame_atual = frame_to
        mover()

    def conectar_arduino(self, porta):
        # se escolher "Simulado" no combo, ativa simulação
        if porta is None or "simul" in porta.lower():
            self.simular_sem_arduino = True
            messagebox = None
        else:
            # tentamos abrir porta com pyserial se disponível
            try:
                import serial
                self.serial = serial.Serial(porta, 9600, timeout=1)
                self.simular_sem_arduino = False
            except Exception as e:
                print("Não foi possível abrir porta serial, usando simulação:", e)
                self.simular_sem_arduino = True

        # vai para seleção de plantas
        self.slide_to(self.frame_porta, self.frame_selecao)

    def ir_para_adicionar(self):
        # atualiza países na tela adicionar
        self.frame_adicionar.update_paises(self.paises_db)
        self.slide_to(self.frame_selecao, self.frame_adicionar)

    def ir_para_selecao(self):
        self.slide_to(self.frame_adicionar, self.frame_selecao)

    def voltar_selecao(self):
        self.ir_para_selecao()

    def atualizar_plantas(self):
        self.plantas_db = carregar_json(ARQ_PLANTAS) or []
        self.frame_selecao.refresh_lista(self.plantas_db)

    def ir_para_adicionar(self):
        self.slide_to(self.frame_selecao, self.frame_adicionar)

    def ir_para_simulacao(self, planta_nome):
        # monta frame de simulação dinamicamente para a planta
        if self.frame_simulacao:
            self.frame_simulacao.place_forget()
        self.frame_simulacao = TelaSimulacao(self, planta_nome, self.ir_para_tamagotchi, self.voltar_para_selecao_from_sim)
        self.frame_simulacao.place(relx=1, rely=0, relwidth=1, relheight=1)
        self.slide_to(self.frame_selecao, self.frame_simulacao)

    def voltar_para_selecao_from_sim(self):
        self.slide_to(self.frame_simulacao, self.frame_selecao)

    def ir_para_tamagotchi(self, planta_nome):
        # cria tela tamagotchi (reutiliza se já existir)
        if self.frame_tamagotchi:
            self.frame_tamagotchi.place_forget()
        self.frame_tamagotchi = TelaTamagotchi(self, planta_nome, self.ir_de_tamagotchi_para_simulacao)
        self.frame_tamagotchi.place(relx=1, rely=0, relwidth=1, relheight=1)
        self.slide_to(self.frame_simulacao, self.frame_tamagotchi)

    def ir_de_tamagotchi_para_simulacao(self):
        # volta pra sim
        if self.frame_tamagotchi and self.frame_simulacao:
            self.slide_to(self.frame_tamagotchi, self.frame_simulacao)

    # ---------- comandos secretos via API ----------
    def process_cmd(self, cmd):
        """F / C / S / N"""
        planta = None
        # tenta obter planta atual: prefer simulação, senão seleção
        if self.frame_simulacao:
            planta = self.frame_simulacao.planta
        else:
            # se tiver seleção, pega valor selecionado
            sel = self.frame_selecao.get_selected()
            planta = sel
        if planta is None:
            print("[segredo] sem planta selecionada")
            return
        # planta é dict com keys: nome,temp_min,temp_max,umidade_min,umidade_max
        p = planta
        if cmd == "F":
            self.temperatura = p["temp_min"] - 1.5
            self.meta_temp = self.temperatura
            if self.frame_tamagotchi: self.frame_tamagotchi.force_image("frio")
            print("[segredo] F aplicado")
        elif cmd == "C":
            self.temperatura = p["temp_max"] + 1.3
            self.meta_temp = self.temperatura
            if self.frame_tamagotchi: self.frame_tamagotchi.force_image("calor")
            print("[segredo] C aplicado")
        elif cmd == "S":
            self.umidade_ar = max(0.0, p["umidade_min"] - 2.0)
            self.meta_umid = self.umidade_ar
            if self.frame_tamagotchi: self.frame_tamagotchi.force_image("arseco")
            print("[segredo] S aplicado")
        elif cmd == "N":
            # normaliza
            self.temperatura = (p["temp_min"] + p["temp_max"]) / 2.0
            self.umidade_ar = (p["umidade_min"] + p["umidade_max"]) / 2.0
            self.meta_temp = 25.0
            self.meta_umid = 55.0
            if self.frame_tamagotchi: self.frame_tamagotchi.clear_forced()
            print("[segredo] N aplicado")
        # atualiza displays imediatos
        if self.frame_simulacao:
            self.frame_simulacao.update_display(self.temperatura, self.umidade_ar)
        if self.frame_tamagotchi:
            self.frame_tamagotchi.update_image(self.temperatura, self.umidade_ar)

    # ---------- loop de simulação física (1s steps) ----------
    def loop_simulacao(self):
        last_meta_adjust = 0
        last_monitor_update = 0
        while self.running:
            agora = time.time()
            # check if tamagotchi manual active
            modo_manual = False
            if self.frame_tamagotchi:
                modo_manual = self.frame_tamagotchi.any_manual_active()
            # metas ajustadas cada 5s se manual
            if modo_manual and (agora - last_meta_adjust >= 5):
                last_meta_adjust = agora
                if self.frame_tamagotchi.ativo_aquecer:
                    self.meta_temp = min(self.meta_temp + 0.1, 40.0)
                elif self.frame_tamagotchi.ativo_resfriar:
                    self.meta_temp = max(self.meta_temp - 0.1, 10.0)
                else:
                    # tende a 25
                    if self.meta_temp > 25.0:
                        self.meta_temp = max(self.meta_temp - 0.05, 25.0)
                    elif self.meta_temp < 25.0:
                        self.meta_temp = min(self.meta_temp + 0.05, 25.0)
                if self.frame_tamagotchi.ativo_umidificar:
                    self.meta_umid = min(self.meta_umid + 0.25, 80.0)
                elif self.frame_tamagotchi.ativo_irrigar:
                    self.meta_umid = min(self.meta_umid + 0.5, 80.0)
                else:
                    if self.meta_umid > 55.0:
                        self.meta_umid = max(self.meta_umid - 0.2, 55.0)
                    elif self.meta_umid < 55.0:
                        self.meta_umid = min(self.meta_umid + 0.2, 55.0)

            # se automático, meta tem derivações suaves
            if not modo_manual:
                self.meta_temp += random.uniform(-0.02, 0.02)
                self.meta_umid += random.uniform(-0.05, 0.05)
                self.meta_temp += (25.0 - self.meta_temp) * 0.001
                self.meta_umid += (55.0 - self.meta_umid) * 0.001
                self.meta_temp = min(max(10.0, self.meta_temp), 40.0)
                self.meta_umid = min(max(20.0, self.meta_umid), 80.0)

            # inércia / suavização (1s step)
            inertia = 0.08
            noise_temp = random.uniform(-0.08, 0.08)
            noise_umid = random.uniform(-0.15, 0.15)
            self.temperatura += (self.meta_temp - self.temperatura) * inertia + noise_temp
            self.umidade_ar += (self.meta_umid - self.umidade_ar) * inertia + noise_umid
            self.temperatura = min(max(10.0, self.temperatura), 40.0)
            self.umidade_ar = min(max(20.0, self.umidade_ar), 80.0)

            # ler solo do arduino simulado
            if self.simular_sem_arduino:
                self.ar_sim.ler_solo()
            else:
                # TODO: ler pela serial real
                pass

            # lógica relés automática (histerese simples)
            desired = {7: False, 11: False, 9: False, 10: False}
            if not modo_manual:
                if self.temperatura < 18.0:
                    desired[7] = True
                elif self.temperatura > 30.0:
                    desired[11] = True
                if self.umidade_ar < 40.0:
                    desired[10] = True
                if any(v < 300 for v in (self.ar_sim.solo if self.simular_sem_arduino else [1023,1023,1023])):
                    desired[10] = True
            else:
                # quando manual, tamagotchi define
                desired[7] = getattr(self.frame_tamagotchi, "ativo_aquecer", False)
                desired[11] = getattr(self.frame_tamagotchi, "ativo_resfriar", False)
                desired[9] = getattr(self.frame_tamagotchi, "ativo_umidificar", False)
                desired[10] = getattr(self.frame_tamagotchi, "ativo_irrigar", False)

            # aplica mudanças (set_relay_state faria serial; aqui apenas registra)
            for p, ligar in desired.items():
                if self.relay_states.get(p) != ligar:
                    self.relay_states[p] = ligar
                    # se for pino 10, também atualiza arduino simulado
                    if p == 10:
                        self.ar_sim.set_pino10(ligar)
                    # enviar comando serial real aqui se necessário

            # atualiza displays com intervalo (5s quando manual, 60s quando automático)
            interval = 5 if modo_manual else 60
            if agora - last_monitor_update >= interval:
                last_monitor_update = agora
                # atualiza frame_simulacao e frame_tamagotchi se visíveis
                try:
                    if self.frame_simulacao:
                        self.frame_simulacao.update_display(self.temperatura, self.umidade_ar)
                    if self.frame_tamagotchi:
                        self.frame_tamagotchi.update_image(self.temperatura, self.umidade_ar)
                except Exception:
                    pass

            time.sleep(1)

    def on_close(self):
        self.running = False
        self.destroy()

# ----------------- Tela Porta -----------------
class TelaPorta(ctk.CTkFrame):
    def __init__(self, master, conectar_callback):
        super().__init__(master, fg_color=CTK_BG)
        ctk.CTkLabel(self, text="🔌 Selecionar Porta Arduino ou Simulação",
                     font=("Arial", 22, "bold"), text_color=CTK_TEXT).pack(pady=28)
        # lista de portas reais
        portas = [p.device for p in serial.tools.list_ports.comports()]
        if not portas:
            portas = ["Simulação (sem Arduino)"]
        self.combo = ctk.CTkComboBox(self, values=portas, width=420)
        self.combo.pack(pady=12)
        self.combo.set(portas[0])
        ctk.CTkButton(self, text="Conectar", width=200, command=lambda: conectar_callback(self.combo.get()),
                      fg_color=CTK_BTN, hover_color=CTK_HOVER).pack(pady=12)

# ----------------- Tela Seleção Planta -----------------
class TelaSelecaoPlanta(ctk.CTkFrame):
    def __init__(self, master, confirmar_callback, adicionar_callback):
        super().__init__(master, fg_color=CTK_BG)
        self.confirmar_callback = confirmar_callback
        self.adicionar_callback = adicionar_callback
        ctk.CTkLabel(self, text="🪴 Selecionar Planta", font=("Arial", 22, "bold"), text_color=CTK_TEXT).pack(pady=20)
        self.combo = ctk.CTkComboBox(self, values=[], width=420)
        self.combo.pack(pady=12)
        btn_frame = ctk.CTkFrame(self, fg_color=CTK_CARD)
        btn_frame.pack(pady=12)
        ctk.CTkButton(btn_frame, text="Selecionar", command=self._selecionar, fg_color=CTK_BTN, hover_color=CTK_HOVER).grid(row=0, column=0, padx=8, pady=8)
        ctk.CTkButton(btn_frame, text="➕ Adicionar Planta", command=self._adicionar, fg_color=CTK_BTN, hover_color=CTK_HOVER).grid(row=0, column=1, padx=8, pady=8)

        self.refresh_lista(master.plantas_db)

    def refresh_lista(self, plantas_list):
        nomes = [p["nome"] for p in plantas_list]
        self.combo.configure(values=nomes)
        if nomes:
            self.combo.set(nomes[0])
        else:
            self.combo.set("")

    def _selecionar(self):
        nome = self.combo.get()
        if not nome:
            messagebox.showwarning("Aviso", "Selecione uma planta.")
            return
        # encontrar dict de planta
        plantas = carregar_json(ARQ_PLANTAS) or []
        p = next((q for q in plantas if q["nome"] == nome), None)
        if p is None:
            messagebox.showerror("Erro", "Parâmetros da planta não encontrados.")
            return
        self.confirmar_callback(p)

    def _adicionar(self):
        self.adicionar_callback()

    def get_selected(self):
        nome = self.combo.get()
        plantas = carregar_json(ARQ_PLANTAS) or []
        return next((q for q in plantas if q["nome"] == nome), None)

# ----------------- Tela Adicionar Planta -----------------
class TelaAdicionarPlanta(ctk.CTkFrame):
    def __init__(self, master, voltar_cb, atualizar_cb, paises_db):
        super().__init__(master, fg_color=CTK_BG)
        self.voltar_cb = voltar_cb
        self.atualizar_cb = atualizar_cb
        self.paises_db = paises_db

        ctk.CTkLabel(self, text="➕ Adicionar/Editar Planta", font=("Arial", 22, "bold"), text_color=CTK_TEXT).pack(pady=12)
        frm = ctk.CTkFrame(self, fg_color=CTK_CARD)
        frm.pack(padx=12, pady=12, fill="x")

        ctk.CTkLabel(frm, text="Nome:", text_color=CTK_TEXT).grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self.entry_nome = ctk.CTkEntry(frm, width=320); self.entry_nome.grid(row=0, column=1, padx=8, pady=6)

        ctk.CTkLabel(frm, text="País (opcional):", text_color=CTK_TEXT).grid(row=1, column=0, sticky="w", padx=8, pady=6)
        self.combo_paises = ctk.CTkComboBox(frm, values=list(self.paises_db.keys()), width=320)
        self.combo_paises.grid(row=1, column=1, padx=8, pady=6)
        self.combo_paises.set("")

        ctk.CTkLabel(frm, text="Temp min (°C):", text_color=CTK_TEXT).grid(row=2, column=0, sticky="w", padx=8, pady=6)
        self.entry_tmin = ctk.CTkEntry(frm, width=120); self.entry_tmin.grid(row=2, column=1, sticky="w", padx=8, pady=6)

        ctk.CTkLabel(frm, text="Temp max (°C):", text_color=CTK_TEXT).grid(row=3, column=0, sticky="w", padx=8, pady=6)
        self.entry_tmax = ctk.CTkEntry(frm, width=120); self.entry_tmax.grid(row=3, column=1, sticky="w", padx=8, pady=6)

        ctk.CTkLabel(frm, text="Umid min (%):", text_color=CTK_TEXT).grid(row=4, column=0, sticky="w", padx=8, pady=6)
        self.entry_umin = ctk.CTkEntry(frm, width=120); self.entry_umin.grid(row=4, column=1, sticky="w", padx=8, pady=6)

        ctk.CTkLabel(frm, text="Umid max (%):", text_color=CTK_TEXT).grid(row=5, column=0, sticky="w", padx=8, pady=6)
        self.entry_umax = ctk.CTkEntry(frm, width=120); self.entry_umax.grid(row=5, column=1, sticky="w", padx=8, pady=6)

        ctk.CTkButton(frm, text="Carregar do país", command=self.load_from_country, fg_color=CTK_BTN).grid(row=6, column=0, padx=8, pady=10)
        ctk.CTkButton(frm, text="Salvar planta", command=self.save_plant, fg_color=CTK_BTN).grid(row=6, column=1, padx=8, pady=10)

        ctk.CTkButton(self, text="Voltar", command=self.voltar, fg_color=CTK_BTN).pack(pady=8)
        self.lbl_status = ctk.CTkLabel(self, text="", text_color=CTK_TEXT)
        self.lbl_status.pack(pady=6)

    def update_paises(self, paises_db):
        self.paises_db = paises_db
        self.combo_paises.configure(values=list(self.paises_db.keys()))

    def load_from_country(self):
        pais = self.combo_paises.get()
        if not pais:
            self.lbl_status.configure(text="Escolha um país.", text_color="red"); return
        dados = self.paises_db.get(pais)
        if not dados:
            self.lbl_status.configure(text="País não encontrado no DB.", text_color="red"); return
        # nomes esperados: temp_min,temp_max,umidade_min,umidade_max ou similar
        self.entry_tmin.delete(0, "end"); self.entry_tmin.insert(0, str(dados.get("temp_min", "")))
        self.entry_tmax.delete(0, "end"); self.entry_tmax.insert(0, str(dados.get("temp_max", "")))
        self.entry_umin.delete(0, "end"); self.entry_umin.insert(0, str(dados.get("umidade_min", dados.get("umid_min", ""))))
        self.entry_umax.delete(0, "end"); self.entry_umax.insert(0, str(dados.get("umidade_max", dados.get("umid_max", ""))))
        self.lbl_status.configure(text=f"Dados de {pais} carregados.", text_color="green")

    def save_plant(self):
        nome = self.entry_nome.get().strip()
        if not nome:
            self.lbl_status.configure(text="Nome obrigatório.", text_color="red"); return
        try:
            tmin = float(self.entry_tmin.get())
            tmax = float(self.entry_tmax.get())
            umin = float(self.entry_umin.get())
            umax = float(self.entry_umax.get())
        except Exception:
            self.lbl_status.configure(text="Valores inválidos.", text_color="red"); return
        if tmin >= tmax or umin >= umax:
            self.lbl_status.configure(text="Mínimos devem ser menores que máximos.", text_color="red"); return
        plantas = carregar_json(ARQ_PLANTAS) or []
        idx = next((i for i,p in enumerate(plantas) if p["nome"].lower() == nome.lower()), None)
        rec = {"nome": nome, "temp_min": tmin, "temp_max": tmax, "umidade_min": umin, "umidade_max": umax}
        if idx is None:
            plantas.append(rec)
        else:
            plantas[idx] = rec
        salvar_json(ARQ_PLANTAS, plantas)
        self.lbl_status.configure(text=f"Planta {nome} salva.", text_color="green")
        # atualizar seleção
        self.atualizar_cb()

    def atualizar_cb(self):
        # chama callback para atualizar lista de plantas no app
        try:
            self.atualizar_cb = self.atualizar_cb
        except Exception:
            pass
        # for safety: if master has method atualizar_plantas
        if hasattr(self.master, 'atualizar_plantas'):
            self.master.atualizar_plantas()

    def voltar(self):
        self.master.atualizar_plantas()
        self.master.slide_to(self, self.master.frame_selecao)

# ----------------- Tela Simulação -----------------
class TelaSimulacao(ctk.CTkFrame):
    def __init__(self, master, planta_dict, abrir_tamagotchi_cb, voltar_cb):
        super().__init__(master, fg_color=CTK_BG)
        self.master = master
        self.planta = planta_dict
        self.abrir_tamagotchi_cb = abrir_tamagotchi_cb
        self.voltar_cb = voltar_cb
        ctk.CTkLabel(self, text=f"🌿 Monitor - {self.planta['nome']}", font=("Arial", 20, "bold"), text_color=CTK_TEXT).pack(pady=12)

        info_frame = ctk.CTkFrame(self, fg_color=CTK_CARD)
        info_frame.pack(padx=12, pady=12, fill="x")

        self.lbl_temp = ctk.CTkLabel(info_frame, text="Temperatura: -- °C", font=("Arial", 16), text_color=CTK_TEXT)
        self.lbl_temp.grid(row=0, column=0, padx=12, pady=10)
        self.lbl_umid = ctk.CTkLabel(info_frame, text="Umidade ar: -- %", font=("Arial", 16), text_color=CTK_TEXT)
        self.lbl_umid.grid(row=0, column=1, padx=12, pady=10)

        # Botões toggle
        btn_frame = ctk.CTkFrame(self, fg_color=CTK_CARD)
        btn_frame.pack(pady=8)
        self.btn_aquecer = ctk.CTkButton(btn_frame, text="Aquecer", command=self.toggle_aquecer, width=120)
        self.btn_resfriar = ctk.CTkButton(btn_frame, text="Resfriar", command=self.toggle_resfriar, width=120)
        self.btn_umid = ctk.CTkButton(btn_frame, text="Umidificar", command=self.toggle_umid, width=120)
        self.btn_irrig = ctk.CTkButton(btn_frame, text="Irrigar", command=self.toggle_irrig, width=120)
        self.btn_aquecer.grid(row=0, column=0, padx=6, pady=6)
        self.btn_resfriar.grid(row=0, column=1, padx=6, pady=6)
        self.btn_umid.grid(row=0, column=2, padx=6, pady=6)
        self.btn_irrig.grid(row=0, column=3, padx=6, pady=6)

        self.btn_auto = ctk.CTkButton(self, text="Voltar ao automático", command=self.voltar_automatico)
        self.btn_auto.pack(pady=8)

        self.btn_open_tama = ctk.CTkButton(self, text="Ir para Tamagotchi", command=lambda: abrir_tamagotchi_cb(self.planta))
        self.btn_open_tama.pack(pady=6)

        self.btn_back = ctk.CTkButton(self, text="Voltar para seleção", command=lambda: self.master.slide_to(self, self.master.frame_selecao))
        self.btn_back.pack(pady=8)

        # estados (ligados por toggles)
        self.manual_estados = {"aquecer": False, "resfriar": False, "umid": False, "irrig": False}
        # define temperatura/umidade inicial com base na planta
        self.temperatura = (self.planta["temp_min"] + self.planta["temp_max"]) / 2.0
        self.umidade = (self.planta["umidade_min"] + self.planta["umidade_max"]) / 2.0

        self.update_display(self.temperatura, self.umidade)

    def update_display(self, temp, umid):
        # chamado pelo loop central
        self.temperatura = temp
        self.umidade = umid
        self.lbl_temp.configure(text=f"Temperatura: {temp:.1f} °C")
        self.lbl_umid.configure(text=f"Umidade do ar: {umid:.1f} %")
        # atualizar cor botões
        def set_btn(btn, estado):
            btn.configure(fg_color="#60a060" if estado else CTK_BTN)
        set_btn(self.btn_aquecer, self.manual_estados["aquecer"])
        set_btn(self.btn_resfriar, self.manual_estados["resfriar"])
        set_btn(self.btn_umid, self.manual_estados["umid"])
        set_btn(self.btn_irrig, self.manual_estados["irrig"])

    # toggles
    def toggle_aquecer(self):
        self.manual_estados["aquecer"] = not self.manual_estados["aquecer"]
        if self.manual_estados["aquecer"]:
            self.manual_estados["resfriar"] = self.manual_estados["umid"] = self.manual_estados["irrig"] = False
        self.apply_manual_to_master()

    def toggle_resfriar(self):
        self.manual_estados["resfriar"] = not self.manual_estados["resfriar"]
        if self.manual_estados["resfriar"]:
            self.manual_estados["aquecer"] = self.manual_estados["umid"] = self.manual_estados["irrig"] = False
        self.apply_manual_to_master()

    def toggle_umid(self):
        self.manual_estados["umid"] = not self.manual_estados["umid"]
        if self.manual_estados["umid"]:
            self.manual_estados["aquecer"] = self.manual_estados["resfriar"] = self.manual_estados["irrig"] = False
        self.apply_manual_to_master()

    def toggle_irrig(self):
        self.manual_estados["irrig"] = not self.manual_estados["irrig"]
        if self.manual_estados["irrig"]:
            self.manual_estados["aquecer"] = self.manual_estados["resfriar"] = self.manual_estados["umid"] = False
        self.apply_manual_to_master()

    def apply_manual_to_master(self):
        # aplica os toggles à tela tamagotchi/master via flags (para loop simulação central usar)
        # cria frame_tamagotchi se não existir para compartilhar estados
        if self.master.frame_tamagotchi:
            t = self.master.frame_tamagotchi
            t.ativo_aquecer = self.manual_estados["aquecer"]
            t.ativo_resfriar = self.manual_estados["resfriar"]
            t.ativo_umidificar = self.manual_estados["umid"]
            t.ativo_irrigar = self.manual_estados["irrig"]
        # atualiza cores imediatamente
        self.update_display(self.temperatura, self.umidade)

    def voltar_automatico(self):
        # desativa todos
        self.manual_estados = {k: False for k in self.manual_estados}
        if self.master.frame_tamagotchi:
            t = self.master.frame_tamagotchi
            t.ativo_aquecer = t.ativo_resfriar = t.ativo_umidificar = t.ativo_irrigar = False
            t.clear_forced()
        self.update_display(self.temperatura, self.umidade)

# ----------------- Tela Tamagotchi -----------------
class TelaTamagotchi(ctk.CTkFrame):
    def __init__(self, master, planta_dict, voltar_cb):
        super().__init__(master, fg_color=CTK_BG)
        self.master = master
        self.planta = planta_dict
        self.voltar_cb = voltar_cb

        ctk.CTkLabel(self, text=f"🌱 Tamagotchi - {self.planta['nome']}", font=("Arial", 22, "bold"), text_color=CTK_TEXT).pack(pady=12)
        self.img_label = ctk.CTkLabel(self, text="", width=320, height=320)
        self.img_label.pack(pady=10)

        # toggles (visíveis aqui também)
        tframe = ctk.CTkFrame(self, fg_color=CTK_CARD)
        tframe.pack(pady=8)
        self.btn_aq = ctk.CTkButton(tframe, text="Aquecer", width=120, command=self.toggle_aquecer)
        self.btn_res = ctk.CTkButton(tframe, text="Resfriar", width=120, command=self.toggle_resfriar)
        self.btn_umid = ctk.CTkButton(tframe, text="Umidificar", width=120, command=self.toggle_umid)
        self.btn_irrig = ctk.CTkButton(tframe, text="Irrigar", width=120, command=self.toggle_irrig)
        self.btn_aq.grid(row=0, column=0, padx=6, pady=6)
        self.btn_res.grid(row=0, column=1, padx=6, pady=6)
        self.btn_umid.grid(row=0, column=2, padx=6, pady=6)
        self.btn_irrig.grid(row=0, column=3, padx=6, pady=6)

        self.btn_back = ctk.CTkButton(self, text="🔙 Voltar para Dados", command=lambda: master.slide_to(self, master.frame_simulacao))
        self.btn_back.pack(pady=10)

        self.btn_auto = ctk.CTkButton(self, text="🔄 Voltar para Automático", command=self.reset_manual)
        self.btn_auto.pack(pady=6)

        # load images
        self.images = {}
        for k in ("frio","calor","seco","arseco","normal"):
            p = os.path.join(PASTA_IMAGENS, f"{k}.png")
            if os.path.exists(p):
                try:
                    img = Image.open(p).resize((320,320), Image.LANCZOS)
                    self.images[k] = ImageTk.PhotoImage(img)
                except Exception as e:
                    self.images[k] = None
            else:
                self.images[k] = None

        # manual flags (compartilhadas com simulação)
        self.ativo_aquecer = False
        self.ativo_resfriar = False
        self.ativo_umidificar = False
        self.ativo_irrigar = False

        # forced image key (usado pelos comandos secretos)
        self.forced = None

        # show initial image
        self.update_image(master.temperatura, master.umidade_ar)

    def update_image(self, temp, umid):
        # se existe forced key, mantém até clean
        if self.forced:
            img = self.images.get(self.forced)
            if img:
                self.img_label.configure(image=img, text="")
                self.img_label.image = img
            else:
                self.img_label.configure(text=f"({self.forced})", image=None)
            return

        # decide com base na planta parametros
        p = self.planta
        if temp < p["temp_min"]:
            key = "frio"
        elif temp > p["temp_max"]:
            key = "calor"
        elif umid < p["umidade_min"]:
            key = "seco"
        elif umid > p["umidade_max"]:
            key = "arseco"
        else:
            key = "normal"

        img = self.images.get(key)
        if img:
            self.img_label.configure(image=img, text="")
            self.img_label.image = img
        else:
            self.img_label.configure(image=None, text=f"Estado: {key}")

    def force_image(self, key):
        self.forced = key
        self.update_image(self.master.temperatura, self.master.umidade_ar)

    def clear_forced(self):
        self.forced = None
        self.update_image(self.master.temperatura, self.master.umidade_ar)

    def any_manual_active(self):
        return self.ativo_aquecer or self.ativo_resfriar or self.ativo_umidificar or self.ativo_irrigar

    def toggle_aquecer(self):
        self.ativo_aquecer = not self.ativo_aquecer
        if self.ativo_aquecer:
            self.ativo_resfriar = self.ativo_umidificar = self.ativo_irrigar = False
        self.sync_with_master()

    def toggle_resfriar(self):
        self.ativo_resfriar = not self.ativo_resfriar
        if self.ativo_resfriar:
            self.ativo_aquecer = self.ativo_umidificar = self.ativo_irrigar = False
        self.sync_with_master()

    def toggle_umid(self):
        self.ativo_umidificar = not self.ativo_umidificar
        if self.ativo_umidificar:
            self.ativo_aquecer = self.ativo_resfriar = self.ativo_irrigar = False
        self.sync_with_master()

    def toggle_irrig(self):
        self.ativo_irrigar = not self.ativo_irrigar
        if self.ativo_irrigar:
            self.ativo_aquecer = self.ativo_resfriar = self.ativo_umidificar = False
        self.sync_with_master()

    def reset_manual(self):
        self.ativo_aquecer = self.ativo_resfriar = self.ativo_umidificar = self.ativo_irrigar = False
        self.clear_forced()
        self.sync_with_master()

    def sync_with_master(self):
        # Update master flags (master.loop_simulacao reads these via frame_tamagotchi)
        # This method simply ensures UI buttons reflect state
        def set_btn(btn, val):
            btn.configure(fg_color="#60a060" if val else CTK_BTN)
        set_btn(self.btn_aq, self.ativo_aquecer)
        set_btn(self.btn_res, self.ativo_resfriar)
        set_btn(self.btn_umid, self.ativo_umidificar)
        set_btn(self.btn_irrig, self.ativo_irrigar)

# ----------------- Run -----------------
if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    # ensure plantas.json exists
    if not os.path.exists(ARQ_PLANTAS):
        salvar_json(ARQ_PLANTAS, [])
    # ensure paises.json exists (if not, create sample)
    if not os.path.exists(ARQ_PAISES):
        sample = {
            "Brasil": {"temp_min": 20, "temp_max": 30, "umidade_min": 50, "umidade_max": 80},
            "Canadá": {"temp_min": -5, "temp_max": 25, "umidade_min": 40, "umidade_max": 70},
            "Japão": {"temp_min": 5, "temp_max": 28, "umidade_min": 45, "umidade_max": 85}
        }
        salvar_json(ARQ_PAISES, sample)
    app.mainloop()
