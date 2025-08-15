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
from openai import OpenAI
import queue

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
        # valores 0..1023 simulados (seco > 700, ideal 350-700, úmido < 350)
        self.solo = [800, 800, 800]
        self.pino10 = False

    def ler_solo(self):
        # pequena oscilação natural
        self.solo = [max(0, min(1023, int(v + random.uniform(-5, 5)))) for v in self.solo]
        # solo seca lentamente
        if not self.pino10:
            self.solo = [min(1023, v + 0.1) for v in self.solo]
        return self.solo

    def irrigar_solo(self):
        # irrigação torna o solo mais úmido (valor diminui)
        self.solo = [max(0, v - 5) for v in self.solo]

    def set_pino10(self, estado):
        self.pino10 = bool(estado)


# ----------------- Tela Assistente -----------------
class TelaAssistente(ctk.CTkFrame):
    def __init__(self, master, voltar_cb):
        super().__init__(master, fg_color=CTK_BG)
        self.master = master
        self.voltar_cb = voltar_cb

        # Configurações do Assistente
        self.client = OpenAI(base_url="http://localhost:11434/v1", api_key="xxx")
        self.CHAR_DELAY = 0.008
        self.PUNCT_PAUSE = 0.14
        self.WORD_ACCEL = True
        self.pensamento_atual = ""
        self.janela_pensamento = None
        self.caixa_pensamento = None
        self.typing_queue = queue.Queue()

        # Interface
        ctk.CTkLabel(self, text="🤖 Assistente Pessoal", font=("Arial", 22, "bold"), text_color=CTK_TEXT).pack(pady=12)
        
        self.chat_textbox = ctk.CTkTextbox(self, wrap="word", fg_color=CTK_CARD, text_color=CTK_TEXT)
        self.chat_textbox.pack(fill="both", expand=True, padx=10, pady=10)
        self.chat_textbox.configure(state="disabled")
        self.chat_textbox.tag_config('bot', foreground="#00FF00")

        entrada_frame = ctk.CTkFrame(self, fg_color="transparent")
        entrada_frame.pack(fill="x", padx=10, pady=6)

        self.entrada = ctk.CTkEntry(entrada_frame, placeholder_text="Digite aqui sua pergunta...", fg_color=CTK_CARD, text_color=CTK_TEXT)
        self.entrada.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.entrada.bind("<Return>", lambda e: self.enviar_msg())

        self.botao_enviar = ctk.CTkButton(entrada_frame, text="Enviar", command=self.enviar_msg, fg_color=CTK_BTN, hover_color=CTK_HOVER)
        self.botao_enviar.pack(side="right")

        self.btn_back = ctk.CTkButton(self, text="🔙 Voltar", command=self.voltar_cb, fg_color=CTK_BTN, hover_color=CTK_HOVER)
        self.btn_back.pack(pady=10)

        # Worker de digitação
        threading.Thread(target=self.typing_worker, daemon=True).start()

    def typing_worker(self):
        while True:
            try:
                segment, tag = self.typing_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if segment is None:
                self.typing_queue.task_done()
                break
            for ch in segment:
                self.chat_textbox.configure(state="normal")
                self.chat_textbox.insert("end", ch, tag)
                self.chat_textbox.configure(state="disabled")
                self.chat_textbox.see("end")
                if self.WORD_ACCEL and ch == " ":
                    time.sleep(max(self.CHAR_DELAY * 0.4, 0))
                else:
                    time.sleep(self.CHAR_DELAY)
                if ch in ".!?":
                    time.sleep(self.PUNCT_PAUSE)
            self.typing_queue.task_done()

    def enviar_msg(self):
        user_msg = self.entrada.get().strip()
        if not user_msg:
            return
        self.entrada.delete(0, "end")
        self.chat_textbox.configure(state="normal")
        self.chat_textbox.insert("end", f"\n\nVocê: {user_msg}\n")
        self.chat_textbox.configure(state="disabled")
        self.chat_textbox.see("end")
        threading.Thread(target=self.resposta_bot, args=(user_msg,), daemon=True).start()

    def resposta_bot(self, user_msg):
        self.pensamento_atual = ""
        self.after(0, lambda: self.mostrar_painel_pensando(True))
        try:
            response = self.client.chat.completions.create(
                model="deepseek-r1:8b",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Você é um agricultor profissional com 30 anos de experiência. "
                            "Responda como um especialista real, sem exageros ou dramatização. "
                            "Se a pergunta for simples (ex.: 'Como plantar batata?'), dê uma resposta prática. "
                            "Se for complexa (ex.: 'Como controlar pragas organicamente?'), explique com detalhes técnicos. "
                            "Mantenha um tom natural, direto e baseado em fatos reais da agricultura."
                            "Não comente mais sobre os comandos anteriores."
                            "Responda da forma mais rápida possivel sem ficar pensando demais."
                        )
                    },
                    {"role": "user", "content": user_msg}
                ],
                stream=True
            )
            pensando = False
            fala_buffer = ""
            primeira_parte = True
            if primeira_parte:
                self.typing_queue.put(("\n\nAssistente: ", 'bot'))
                primeira_parte = False

            for chunk in response:
                if chunk.choices[0].delta.content:
                    parte = chunk.choices[0].delta.content
                    if "<think>" in parte:
                        pensando = True; parte = parte.replace("<think>", "")
                    if "</think>" in parte:
                        pensando = False; parte = parte.replace("</think>", "")
                    if pensando:
                        self.pensamento_atual += parte
                        self.after(0, self.atualizar_pensamento_ao_vivo, parte)
                    else:
                        fala_buffer += parte
            if fala_buffer.strip():
                self.typing_queue.put((fala_buffer, 'bot'))
        except Exception as e:
            error_msg = f"\n[Erro] Não foi possível conectar ao assistente. Verifique se o servidor local está rodando.\nDetalhes: {str(e)}\n"
            self.typing_queue.put((error_msg, 'bot'))
        finally:
            self.after(0, lambda: self.mostrar_painel_pensando(False))

    def atualizar_pensamento_ao_vivo(self, parte):
        if self.caixa_pensamento:
            self.caixa_pensamento.configure(state="normal")
            self.caixa_pensamento.insert("end", parte)
            self.caixa_pensamento.configure(state="disabled")
            self.caixa_pensamento.see("end")

    def mostrar_painel_pensando(self, mostrar):
        if mostrar:
            if not hasattr(self, "btn_pensando") or self.btn_pensando is None:
                self.btn_pensando = ctk.CTkButton(
                    self,
                    text="💭 Assistente está pensando... (clique para ver)",
                    command=self.mostrar_pensamento,
                    fg_color="#444444",
                    hover_color="#555555"
                )
                self.btn_pensando.pack(side="bottom", fill="x", pady=3, padx=10)
        else:
            if hasattr(self, "btn_pensando") and self.btn_pensando:
                self.btn_pensando.destroy()
                self.btn_pensando = None

    def mostrar_pensamento(self):
        if self.janela_pensamento and self.janela_pensamento.winfo_exists():
            self.janela_pensamento.lift()
            return
        self.janela_pensamento = ctk.CTkToplevel(self.master)
        self.janela_pensamento.title("💭 Pensamento do Assistente")
        self.janela_pensamento.geometry("500x400")
        self.caixa_pensamento = ctk.CTkTextbox(self.janela_pensamento, wrap="word", fg_color=CTK_CARD, text_color=CTK_TEXT)
        self.caixa_pensamento.pack(fill="both", expand=True, padx=10, pady=10)
        self.caixa_pensamento.insert("end", self.pensamento_atual)
        self.caixa_pensamento.configure(state="disabled")

# ----------------- Main App -----------------
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("🌿 Estufa Inteligente - Sistema Plantas")
        self.geometry("900x620")
        self.configure(bg=CTK_BG)

        # estado global
        self.arduino_porta = None
        self.ar_sim = ArduinoSim()
        self.simular_sem_arduino = True

        self.plantas_db = carregar_json(ARQ_PLANTAS) or []
        self.paises_db = carregar_json(ARQ_PAISES) or {}

        self.temperatura = 25.0
        self.umidade_ar = 55.0
        self.meta_temp = 25.0
        self.meta_umid = 55.0
        self.loop_counter = 0

        self.relay_states = {7: False, 9: False, 10: False, 11: False}

        # UI frames
        self.frame_porta = TelaPorta(self, self.conectar_arduino)
        self.frame_selecao = TelaSelecaoPlanta(self, self.ir_para_simulacao, self.ir_para_adicionar)
        self.frame_adicionar = TelaAdicionarPlanta(self, self.voltar_selecao, self.atualizar_plantas, self.paises_db)
        self.frame_simulacao = None
        self.frame_tamagotchi = None
        self.frame_assistente = TelaAssistente(self, self.voltar_para_frame_anterior)
        self.frame_anterior_assistente = None

        for f in (self.frame_porta, self.frame_selecao, self.frame_adicionar, self.frame_assistente):
            if f: f.place(relx=1, rely=0, relwidth=1, relheight=1)
        self.frame_porta.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.frame_atual = self.frame_porta

        self.btn_assistente = ctk.CTkButton(self, text="🤖\nAssistente\nPessoal",
                                           command=self.ir_para_assistente,
                                           fg_color=CTK_BTN, hover_color=CTK_HOVER,
                                           width=80, height=80, corner_radius=40)
        self.btn_assistente.place(relx=0.98, rely=0.98, anchor="se")
        self.btn_assistente.lift()

        self.bind_all('<Control-Key-f>', lambda e: self.process_cmd("F"))
        self.bind_all('<Control-Key-c>', lambda e: self.process_cmd("C"))
        self.bind_all('<Control-Key-s>', lambda e: self.process_cmd("S"))
        self.bind_all('<Control-Key-n>', lambda e: self.process_cmd("N"))

        self.running = True
        threading.Thread(target=self.loop_simulacao, daemon=True).start()

    def slide_to(self, frame_from, frame_to, speed=0.03):
        if not frame_from or not frame_to: return
        self.btn_assistente.lift()
        frame_to.place(relx=1, rely=0, relwidth=1, relheight=1)
        def mover():
            relx = float(frame_to.place_info()['relx'])
            if relx > 0:
                nova = max(0, relx - speed)
                frame_to.place_configure(relx=nova)
                frame_from.place_configure(relx=nova - 1)
                self.after(12, mover)
            else:
                #frame_from.place_forget() # Não usar, causa piscar
                frame_to.place(relx=0, rely=0, relwidth=1, relheight=1)
                self.frame_atual = frame_to
                self.btn_assistente.lift()
        mover()

    def conectar_arduino(self, porta):
        if porta is None or "simul" in porta.lower():
            self.simular_sem_arduino = True
        else:
            try:
                import serial
                self.serial = serial.Serial(porta, 9600, timeout=1)
                self.simular_sem_arduino = False
            except Exception as e:
                messagebox.showerror("Erro Serial", f"Não foi possível abrir a porta serial {porta}.\nUsando modo de simulação.\n\nErro: {e}")
                self.simular_sem_arduino = True
        self.slide_to(self.frame_porta, self.frame_selecao)

    def ir_para_adicionar(self):
        self.frame_adicionar.update_paises(self.paises_db)
        self.slide_to(self.frame_selecao, self.frame_adicionar)

    def voltar_selecao(self):
        self.slide_to(self.frame_adicionar, self.frame_selecao)

    def atualizar_plantas(self):
        self.plantas_db = carregar_json(ARQ_PLANTAS) or []
        self.frame_selecao.refresh_lista(self.plantas_db)

    def ir_para_simulacao(self, planta_dict):
        if self.frame_simulacao: self.frame_simulacao.destroy()
        self.frame_simulacao = TelaSimulacao(self, planta_dict, self.ir_para_tamagotchi, self.voltar_para_selecao_from_sim)
        self.slide_to(self.frame_selecao, self.frame_simulacao)

    def voltar_para_selecao_from_sim(self):
        self.slide_to(self.frame_simulacao, self.frame_selecao)

    def ir_para_tamagotchi(self, planta_dict):
        if self.frame_tamagotchi: self.frame_tamagotchi.destroy()
        self.frame_tamagotchi = TelaTamagotchi(self, planta_dict, self.ir_de_tamagotchi_para_simulacao)
        self.slide_to(self.frame_simulacao, self.frame_tamagotchi)

    def ir_de_tamagotchi_para_simulacao(self):
        self.slide_to(self.frame_tamagotchi, self.frame_simulacao)

    def ir_para_assistente(self):
        self.frame_anterior_assistente = self.frame_atual
        self.slide_to(self.frame_atual, self.frame_assistente)

    def voltar_para_frame_anterior(self):
        if self.frame_anterior_assistente:
            self.slide_to(self.frame_assistente, self.frame_anterior_assistente)

    def process_cmd(self, cmd):
        planta = getattr(self.frame_atual, 'planta', None) or (self.frame_selecao.get_selected() if self.frame_atual == self.frame_selecao else None)
        if not planta: print("[segredo] sem planta selecionada"); return
        
        p = planta
        if cmd == "F": self.temperatura = p["temp_min"] - 1.3
        elif cmd == "C": self.temperatura = p["temp_max"] + 1.1
        elif cmd == "S": self.umidade_ar = max(0.0, p["umidade_min"] - 2.6)
        elif cmd == "N":
            self.temperatura = (p["temp_min"] + p["temp_max"]) / 2.0
            self.umidade_ar = (p["umidade_min"] + p["umidade_max"]) / 2.0
        
        print(f"[segredo] {cmd} aplicado")
        if self.frame_tamagotchi and self.frame_tamagotchi.winfo_exists():
            image_key = {"F": "frio", "C": "calor", "S": "seco"}.get(cmd)
            if image_key: self.frame_tamagotchi.force_image(image_key)
            if cmd == "N": self.frame_tamagotchi.clear_forced()

    def loop_simulacao(self):
        while self.running:
            self.loop_counter += 1
            modo_manual = self.frame_tamagotchi and self.frame_tamagotchi.winfo_exists() and self.frame_tamagotchi.any_manual_active()
            
            # --- Lógica de Metas (Manual vs. Automático) ---
            if modo_manual:
                if self.loop_counter % 3 == 0: # Aplica o efeito a cada 3 segundos
                    t = self.frame_tamagotchi
                    if t.ativo_aquecer: self.meta_temp += 0.1
                    if t.ativo_resfriar: self.meta_temp -= 0.1
                    if t.ativo_umidificar: self.meta_umid += 0.1
                    if t.ativo_irrigar:
                        self.meta_umid += 0.1
                        self.ar_sim.irrigar_solo()
            else: # modo automático
                # Tende a voltar para o normal
                self.meta_temp += (25.0 - self.meta_temp) * 0.01 + random.uniform(-0.02, 0.02)
                self.meta_umid += (55.0 - self.meta_umid) * 0.01 + random.uniform(-0.05, 0.05)
            
            # Limites de metas
            self.meta_temp = min(max(10.0, self.meta_temp), 40.0)
            self.meta_umid = min(max(20.0, self.meta_umid), 90.0)
            
            # --- Simulação Física (Inércia) ---
            self.temperatura += (self.meta_temp - self.temperatura) * 0.1 + random.uniform(-0.05, 0.05)
            self.umidade_ar += (self.meta_umid - self.umidade_ar) * 0.1 + random.uniform(-0.1, 0.1)
            
            # Leitura de Sensores
            if self.simular_sem_arduino: self.ar_sim.ler_solo()
            
            # --- Atualização da UI ---
            try:
                if self.frame_simulacao and self.frame_simulacao.winfo_exists():
                    self.frame_simulacao.update_display(self.temperatura, self.umidade_ar)
                if self.frame_tamagotchi and self.frame_tamagotchi.winfo_exists():
                    self.frame_tamagotchi.update_status(self.temperatura, self.umidade_ar)
            except Exception: pass
            
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
        try:
            portas = [p.device for p in serial.tools.list_ports.comports()] or ["Simulação (sem Arduino)"]
        except Exception:
            portas = ["Simulação (sem Arduino)"]
        self.combo = ctk.CTkComboBox(self, values=portas, width=420, fg_color=CTK_CARD, text_color=CTK_TEXT)
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
        self.combo = ctk.CTkComboBox(self, values=[], width=420, fg_color=CTK_CARD, text_color=CTK_TEXT)
        self.combo.pack(pady=12)
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=12)
        ctk.CTkButton(btn_frame, text="Selecionar", command=self._selecionar, fg_color=CTK_BTN, hover_color=CTK_HOVER).grid(row=0, column=0, padx=8, pady=8)
        ctk.CTkButton(btn_frame, text="➕ Adicionar Planta", command=self._adicionar, fg_color=CTK_BTN, hover_color=CTK_HOVER).grid(row=0, column=1, padx=8, pady=8)
        self.refresh_lista(master.plantas_db)

    def refresh_lista(self, plantas_list):
        nomes = [p["nome"] for p in plantas_list]
        self.combo.configure(values=nomes)
        self.combo.set(nomes[0] if nomes else "")

    def _selecionar(self):
        nome = self.combo.get()
        if not nome:
            messagebox.showwarning("Aviso", "Selecione uma planta.")
            return
        p = self.get_selected()
        if p is None:
            messagebox.showerror("Erro", "Parâmetros da planta não encontrados.")
            return
        self.confirmar_callback(p)

    def _adicionar(self):
        self.adicionar_callback()

    def get_selected(self):
        nome = self.combo.get()
        plantas = carregar_json(ARQ_PLANTAS) or []
        return next((p for p in plantas if p["nome"] == nome), None)

# ----------------- Tela Adicionar Planta -----------------
class TelaAdicionarPlanta(ctk.CTkFrame):
    def __init__(self, master, voltar_cb, atualizar_cb, paises_db):
        super().__init__(master, fg_color=CTK_BG)
        self.master = master
        self.voltar_cb = voltar_cb
        self.atualizar_cb = atualizar_cb
        self.paises_db = paises_db

        ctk.CTkLabel(self, text="➕ Adicionar/Editar Planta", font=("Arial", 22, "bold"), text_color=CTK_TEXT).pack(pady=12)
        frm = ctk.CTkFrame(self, fg_color=CTK_CARD)
        frm.pack(padx=12, pady=12, fill="x")

        # Layout
        fields = {"Nome:": "entry_nome", "País (opcional):": "combo_paises", "Temp min (°C):": "entry_tmin",
                  "Temp max (°C):": "entry_tmax", "Umid min (%):": "entry_umin", "Umid max (%):": "entry_umax"}
        for i, (text, name) in enumerate(fields.items()):
            ctk.CTkLabel(frm, text=text, text_color=CTK_TEXT).grid(row=i, column=0, sticky="w", padx=8, pady=6)
            if "combo" in name:
                widget = ctk.CTkComboBox(frm, values=list(self.paises_db.keys()), width=320, fg_color=CTK_BG, text_color=CTK_TEXT)
                widget.set("")
            else:
                widget = ctk.CTkEntry(frm, width=320 if "nome" in name else 120, fg_color=CTK_BG, text_color=CTK_TEXT)
            widget.grid(row=i, column=1, sticky="w", padx=8, pady=6)
            setattr(self, name, widget)

        btn_frm = ctk.CTkFrame(frm, fg_color="transparent")
        btn_frm.grid(row=len(fields), columnspan=2, pady=10)
        ctk.CTkButton(btn_frm, text="Carregar do país", command=self.load_from_country, fg_color=CTK_BTN, hover_color=CTK_HOVER).pack(side="left", padx=8)
        ctk.CTkButton(btn_frm, text="Salvar planta", command=self.save_plant, fg_color=CTK_BTN, hover_color=CTK_HOVER).pack(side="left", padx=8)

        ctk.CTkButton(self, text="Voltar", command=self.voltar_cb, fg_color=CTK_BTN, hover_color=CTK_HOVER).pack(pady=8)
        self.lbl_status = ctk.CTkLabel(self, text="", text_color=CTK_TEXT)
        self.lbl_status.pack(pady=6)

    def update_paises(self, paises_db):
        self.paises_db = paises_db
        self.combo_paises.configure(values=list(self.paises_db.keys()))

    def load_from_country(self):
        pais = self.combo_paises.get()
        if not pais or pais not in self.paises_db:
            self.lbl_status.configure(text="Escolha um país válido.", text_color="orange"); return
        dados = self.paises_db[pais]
        self.entry_tmin.delete(0, "end"); self.entry_tmin.insert(0, str(dados.get("temp_min", "")))
        self.entry_tmax.delete(0, "end"); self.entry_tmax.insert(0, str(dados.get("temp_max", "")))
        self.entry_umin.delete(0, "end"); self.entry_umin.insert(0, str(dados.get("umidade_min", "")))
        self.entry_umax.delete(0, "end"); self.entry_umax.insert(0, str(dados.get("umidade_umax", "")))
        self.lbl_status.configure(text=f"Dados de {pais} carregados.", text_color="lightgreen")

    def save_plant(self):
        nome = self.entry_nome.get().strip()
        if not nome:
            self.lbl_status.configure(text="Nome da planta é obrigatório.", text_color="orange"); return
        try:
            rec = {
                "nome": nome,
                "temp_min": float(self.entry_tmin.get()), "temp_max": float(self.entry_tmax.get()),
                "umidade_min": float(self.entry_umin.get()), "umidade_max": float(self.entry_umax.get())
            }
            if rec["temp_min"] >= rec["temp_max"] or rec["umidade_min"] >= rec["umidade_max"]:
                self.lbl_status.configure(text="Valores mínimos devem ser menores que os máximos.", text_color="orange"); return
        except ValueError:
            self.lbl_status.configure(text="Todos os campos de valores devem ser numéricos.", text_color="orange"); return
        
        plantas = carregar_json(ARQ_PLANTAS) or []
        idx = next((i for i, p in enumerate(plantas) if p["nome"].lower() == nome.lower()), None)
        if idx is not None: plantas[idx] = rec
        else: plantas.append(rec)
        salvar_json(ARQ_PLANTAS, plantas)
        self.lbl_status.configure(text=f"Planta '{nome}' salva com sucesso!", text_color="lightgreen")
        self.atualizar_cb()


# ----------------- Tela Simulação -----------------
class TelaSimulacao(ctk.CTkFrame):
    def __init__(self, master, planta_dict, abrir_tamagotchi_cb, voltar_cb):
        super().__init__(master, fg_color=CTK_BG)
        self.master = master
        self.planta = planta_dict
        ctk.CTkLabel(self, text=f"🌿 Monitor - {self.planta['nome']}", font=("Arial", 20, "bold"), text_color=CTK_TEXT).pack(pady=12)

        info_frame = ctk.CTkFrame(self, fg_color=CTK_CARD)
        info_frame.pack(padx=12, pady=12, fill="x")
        self.lbl_temp = ctk.CTkLabel(info_frame, text="Temperatura: -- °C", font=("Arial", 16), text_color=CTK_TEXT)
        self.lbl_temp.pack(pady=5)
        self.lbl_umid = ctk.CTkLabel(info_frame, text="Umidade ar: -- %", font=("Arial", 16), text_color=CTK_TEXT)
        self.lbl_umid.pack(pady=5)

        ctk.CTkButton(self, text="Ir para Tamagotchi 🌱", command=lambda: abrir_tamagotchi_cb(self.planta), fg_color=CTK_BTN, hover_color=CTK_HOVER).pack(pady=12)
        ctk.CTkButton(self, text="Voltar para seleção", command=voltar_cb, fg_color=CTK_BTN, hover_color=CTK_HOVER).pack(pady=8)
        
        self.update_display(master.temperatura, master.umidade_ar)

    def update_display(self, temp, umid):
        self.lbl_temp.configure(text=f"Temperatura: {temp:.1f} °C")
        self.lbl_umid.configure(text=f"Umidade do ar: {umid:.1f} %")
        p = self.planta
        if temp < p['temp_min']: self.lbl_temp.configure(text_color="lightblue")
        elif temp > p['temp_max']: self.lbl_temp.configure(text_color="orange")
        else: self.lbl_temp.configure(text_color=CTK_TEXT)
        if umid < p['umidade_min']: self.lbl_umid.configure(text_color="yellow")
        elif umid > p['umidade_max']: self.lbl_umid.configure(text_color="lightcoral")
        else: self.lbl_umid.configure(text_color=CTK_TEXT)

# ----------------- Tela Tamagotchi -----------------
class TelaTamagotchi(ctk.CTkFrame):
    def __init__(self, master, planta_dict, voltar_cb):
        super().__init__(master, fg_color=CTK_BG)
        self.master = master
        self.planta = planta_dict
        
        ctk.CTkLabel(self, text=f"🌱 Tamagotchi - {self.planta['nome']}", font=("Arial", 22, "bold"), text_color=CTK_TEXT).pack(pady=8)
        
        # --- Frame da Imagem e Dados ---
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(pady=5, padx=10, fill="both", expand=True)

        self.img_label = ctk.CTkLabel(main_frame, text="", width=280, height=280)
        self.img_label.pack(pady=5)
        
        # --- Frame para os dados exibidos ---
        info_frame = ctk.CTkFrame(self, fg_color=CTK_CARD)
        info_frame.pack(padx=12, pady=5, fill="x")
        self.lbl_temp = ctk.CTkLabel(info_frame, text="Temperatura: -- °C", font=("Arial", 16), text_color=CTK_TEXT)
        self.lbl_temp.pack(pady=2)
        self.lbl_umid = ctk.CTkLabel(info_frame, text="Umidade ar: -- %", font=("Arial", 16), text_color=CTK_TEXT)
        self.lbl_umid.pack(pady=2)

        # --- Frame para os botões de controle ---
        tframe = ctk.CTkFrame(self, fg_color="transparent")
        tframe.pack(pady=5)
        self.buttons = {
            "Aquecer": ctk.CTkButton(tframe, text="🔥 Aquecer", width=140, command=self.toggle_aquecer),
            "Resfriar": ctk.CTkButton(tframe, text="❄️ Resfriar", width=140, command=self.toggle_resfriar),
            "Umidificar": ctk.CTkButton(tframe, text="💧 Umidificar", width=140, command=self.toggle_umid),
            "Irrigar": ctk.CTkButton(tframe, text="🚿 Irrigar", width=140, command=self.toggle_irrig)
        }
        self.buttons["Aquecer"].grid(row=0, column=0, padx=5, pady=5)
        self.buttons["Resfriar"].grid(row=0, column=1, padx=5, pady=5)
        self.buttons["Umidificar"].grid(row=1, column=0, padx=5, pady=5)
        self.buttons["Irrigar"].grid(row=1, column=1, padx=5, pady=5)

        # --- Frame para botões de navegação ---
        nav_frame = ctk.CTkFrame(self, fg_color="transparent")
        nav_frame.pack(pady=8)
        ctk.CTkButton(nav_frame, text="🔙 Voltar para Dados", command=voltar_cb, fg_color=CTK_BTN, hover_color=CTK_HOVER).pack(side="left", padx=5)
        ctk.CTkButton(nav_frame, text="🔄 Voltar para Automático", command=self.reset_manual, fg_color=CTK_BTN, hover_color=CTK_HOVER).pack(side="left", padx=5)

        self.images = {}
        for k in ("frio", "calor", "normal"):
            p = os.path.join(PASTA_IMAGENS, f"{k}.png")
            if os.path.exists(p):
                try:
                    img = Image.open(p).resize((280, 280), Image.LANCZOS)
                    self.images[k] = ImageTk.PhotoImage(img)
                except Exception as e:
                    print(f"Erro ao carregar imagem {p}: {e}")
                    self.images[k] = None

        self.ativo_aquecer = self.ativo_resfriar = self.ativo_umidificar = self.ativo_irrigar = False
        self.forced = None
        self.sync_buttons()
        self.update_status(master.temperatura, master.umidade_ar)

    def update_status(self, temp, umid):
        # Atualiza a imagem
        key = self.forced
        if not key:
            p = self.planta
            if temp < p["temp_min"]: key = "frio"
            elif temp > p["temp_max"]: key = "calor"
            else: key = "normal"
        
        img = self.images.get(key)
        if img:
            self.img_label.configure(image=img, text="")
            self.img_label.image = img
        else:
            self.img_label.configure(image=None, text=f"Estado: {key}\n(imagem não encontrada)")

        # Atualiza os labels com os dados e cores
        self.lbl_temp.configure(text=f"Temperatura: {temp:.1f} °C")
        self.lbl_umid.configure(text=f"Umidade do ar: {umid:.1f} %")

        p = self.planta
        # Cor para temperatura
        if temp < p['temp_min']: self.lbl_temp.configure(text_color="lightblue")
        elif temp > p['temp_max']: self.lbl_temp.configure(text_color="orange")
        else: self.lbl_temp.configure(text_color=CTK_TEXT)
        # Cor para umidade do ar
        if umid < p['umidade_min']: self.lbl_umid.configure(text_color="yellow")
        else: self.lbl_umid.configure(text_color=CTK_TEXT)

    def force_image(self, key):
        self.forced = key

    def clear_forced(self):
        self.forced = None

    def any_manual_active(self):
        return any([self.ativo_aquecer, self.ativo_resfriar, self.ativo_umidificar, self.ativo_irrigar])

    def _toggle_state(self, key):
        states = {"Aquecer": "ativo_aquecer", "Resfriar": "ativo_resfriar", "Umidificar": "ativo_umidificar", "Irrigar": "ativo_irrigar"}
        current_val = getattr(self, states[key])
        self.reset_manual(sync=False) # Desativa todos antes de ativar um
        setattr(self, states[key], not current_val)
        self.sync_buttons()

    def toggle_aquecer(self): self._toggle_state("Aquecer")
    def toggle_resfriar(self): self._toggle_state("Resfriar")
    def toggle_umid(self): self._toggle_state("Umidificar")
    def toggle_irrig(self): self._toggle_state("Irrigar")

    def reset_manual(self, sync=True):
        self.ativo_aquecer = self.ativo_resfriar = self.ativo_umidificar = self.ativo_irrigar = False
        self.clear_forced()
        if sync: self.sync_buttons()

    def sync_buttons(self):
        states = {"Aquecer": self.ativo_aquecer, "Resfriar": self.ativo_resfriar, "Umidificar": self.ativo_umidificar, "Irrigar": self.ativo_irrigar}
        for name, active in states.items():
            self.buttons[name].configure(fg_color="#60a060" if active else CTK_BTN, hover_color=CTK_HOVER)

# ----------------- Run -----------------
if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    if not os.path.exists(ARQ_PLANTAS):
        salvar_json(ARQ_PLANTAS, [])
    if not os.path.exists(ARQ_PAISES):
        sample = {
            "Brasil": {"temp_min": 20, "temp_max": 30, "umidade_min": 50, "umidade_max": 80},
            "Canadá": {"temp_min": -5, "temp_max": 25, "umidade_min": 40, "umidade_max": 70},
            "Japão": {"temp_min": 5, "temp_max": 28, "umidade_min": 45, "umidade_max": 85}
        }
        salvar_json(ARQ_PAISES, sample)
    if not os.path.exists(PASTA_IMAGENS):
        os.makedirs(PASTA_IMAGENS)
        print(f"Pasta '{PASTA_IMAGENS}' criada. Adicione as imagens 'normal.png', 'frio.png', etc. nesta pasta.")
    app.mainloop()
