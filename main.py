import customtkinter as ctk
import serial.tools.list_ports
import serial
import threading
import time
import json
import requests
from PIL import Image, ImageTk
import os
from CTkMessagebox import CTkMessagebox

# ----- CONFIG -----
OPENWEATHER_API_KEY = '4f3fe2ef4065111f534a8984068b778b'  # Pegue grátis em https://openweathermap.org/api
SIMULACAO_INTERVALO = 3  # segundos
PLANTAS_JSON = 'plantas.json'
PASTA_PLANTAS_IMG = 'plantas'  # pasta com as imagens

# ----- Modelo Planta -----
class Planta:
    def __init__(self, nome, temp_min, temp_max, umid_min, umid_max, pais=None):
        self.nome = nome
        self.temp_min = temp_min
        self.temp_max = temp_max
        self.umid_min = umid_min
        self.umid_max = umid_max
        self.pais = pais

# ----- Gerenciar plantas -----
def salvar_plantas(plantas):
    data = [pl.__dict__ for pl in plantas]
    with open(PLANTAS_JSON, 'w') as f:
        json.dump(data, f)

def carregar_plantas():
    if not os.path.exists(PLANTAS_JSON):
        return []
    with open(PLANTAS_JSON) as f:
        data = json.load(f)
        plantas = []
        for p in data:
            plantas.append(Planta(**p))
        return plantas

# ----- API clima (pegar temperatura e umidade médias do país) -----
def pegar_clima_por_pais(pais):
    # Usar OpenWeather - pega dados da capital do país (simplificado)
    url = f"http://api.openweathermap.org/data/2.5/weather?q={pais}&appid={OPENWEATHER_API_KEY}&units=metric&lang=pt"
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            j = r.json()
            temp = j['main']['temp']
            umid = j['main']['humidity']
            return temp, umid
        else:
            return None, None
    except:
        return None, None

# ----- App -----
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Controle Arduino Plantas")
        self.geometry("600x400")
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.serial_port = None
        self.arduino = None
        self.thread_rodando = False
        self.plantas = carregar_plantas()
        self.planta_selecionada = None

        # Variáveis de simulação
        self.temp_sim = 20
        self.umid_sim = 50
        self.tamagotchi_ativo = False

        self.frames = {}
        for F in (TelaPortas, TelaPlantas, TelaMonitoramento, TelaTamagotchi, TelaAddPlanta):
            frame = F(self)
            self.frames[F] = frame
            frame.grid(row=0, column=0, sticky="nsew")

        self.show_frame(TelaPortas)

    def show_frame(self, container):
        frame = self.frames[container]
        frame.tkraise()

    def conectar_arduino(self, porta):
        try:
            self.arduino = serial.Serial(porta, 9600, timeout=1)
            time.sleep(2)
            self.serial_port = porta
            self.thread_rodando = True
            threading.Thread(target=self.leitura_serial, daemon=True).start()
            print(f"Conectado ao Arduino na porta {porta}")
            self.show_frame(TelaPlantas)
        except Exception as e:
            CTkMessagebox(title="Erro", message=f"Erro ao conectar: {e}", icon="cancel")

    def leitura_serial(self):
        while self.thread_rodando:
            if self.arduino and self.arduino.in_waiting:
                try:
                    linha = self.arduino.readline().decode('utf-8').strip()
                    if linha.startswith("SOLO:"):
                        dados = linha[5:].split(",")
                        solo = list(map(int, dados))
                        # print("Solo:", solo)
                        # Se solo seco e tamagotchi OFF, liga porta 10
                        if not self.tamagotchi_ativo and any(s < 400 for s in solo):
                            self.enviar_comando_arduino("IRRIGACAO ON")
                        else:
                            self.enviar_comando_arduino("IRRIGACAO OFF")
                except:
                    pass
            time.sleep(1)

    def enviar_comando_arduino(self, comando):
        if self.arduino and self.arduino.is_open:
            try:
                self.arduino.write((comando + "\n").encode('utf-8'))
            except Exception as e:
                print("Erro ao enviar comando:", e)

    def alternar_simulacao(self):
        if not self.planta_selecionada:
            return
        # Alterna temp e umid entre valores para simular vida real
        # Exemplo simples: oscila entre +- 5 graus/umid do mínimo/máximo

        import random

        tmin, tmax = self.planta_selecionada.temp_min, self.planta_selecionada.temp_max
        umin, umax = self.planta_selecionada.umid_min, self.planta_selecionada.umid_max

        # alterna temperatura: se menor que min, liga pino 7; se maior que max, liga pino 11
        if self.temp_sim <= tmin:
            self.enviar_comando_arduino("TEMP_BAIXA ON")
            self.enviar_comando_arduino("TEMP_ALTA OFF")
        elif self.temp_sim >= tmax:
            self.enviar_comando_arduino("TEMP_BAIXA OFF")
            self.enviar_comando_arduino("TEMP_ALTA ON")
        else:
            self.enviar_comando_arduino("TEMP_BAIXA OFF")
            self.enviar_comando_arduino("TEMP_ALTA OFF")

        # umidade do ar: se menor que mínimo, liga pino 9 (UMID)
        if self.umid_sim <= umin:
            self.enviar_comando_arduino("UMID ON")
        else:
            self.enviar_comando_arduino("UMID OFF")

        # Atualiza valores simulados (oscila +- 2%)
        self.temp_sim += random.choice([-1, 1]) * random.uniform(0, 2)
        self.temp_sim = max(min(self.temp_sim, tmax + 5), tmin - 5)

        self.umid_sim += random.choice([-1, 1]) * random.uniform(0, 3)
        self.umid_sim = max(min(self.umid_sim, umax + 10), umin - 10)

        # Atualizar labels na tela monitoramento se aberto
        frame = self.frames[TelaMonitoramento]
        if frame.winfo_ismapped():
            frame.lbl_temp.configure(text=f"Temperatura: {self.temp_sim:.1f} °C")
            frame.lbl_umid.configure(text=f"Umidade: {self.umid_sim:.1f} %")

        # Repetir a cada SIMULACAO_INTERVALO segundos
        if not self.tamagotchi_ativo:
            self.after(SIMULACAO_INTERVALO * 1000, self.alternar_simulacao)

    def iniciar_simulacao(self):
        self.temp_sim = (self.planta_selecionada.temp_min + self.planta_selecionada.temp_max) / 2
        self.umid_sim = (self.planta_selecionada.umid_min + self.planta_selecionada.umid_max) / 2
        self.alternar_simulacao()

    def entrar_tamagotchi(self):
        self.tamagotchi_ativo = True
        self.show_frame(TelaTamagotchi)

    def sair_tamagotchi(self):
        self.tamagotchi_ativo = False
        # Desliga todos os pinos do tamagotchi
        self.enviar_comando_arduino("TEMP_BAIXA OFF")
        self.enviar_comando_arduino("TEMP_ALTA OFF")
        self.enviar_comando_arduino("UMID OFF")
        self.enviar_comando_arduino("IRRIGACAO OFF")
        self.show_frame(TelaMonitoramento)
        self.iniciar_simulacao()

    def on_close(self):
        self.thread_rodando = False
        if self.arduino and self.arduino.is_open:
            self.arduino.close()
        self.destroy()

# --- Telas ---

class TelaPortas(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master)
        ctk.CTkLabel(self, text="Selecione a porta do Arduino").pack(pady=10)
        self.combo = ctk.CTkComboBox(self, values=self.listar_portas())
        self.combo.pack(pady=10)
        ctk.CTkButton(self, text="Conectar", command=self.conectar).pack(pady=10)

    def listar_portas(self):
        portas = serial.tools.list_ports.comports()
        return [p.device for p in portas]

    def conectar(self):
        porta = self.combo.get()
        if not porta:
            ctk.CTkMessageBox.show_error("Erro", "Selecione uma porta válida")
            return
        self.master.conectar_arduino(porta)

class TelaPlantas(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master)

        ctk.CTkLabel(self, text="Selecione a planta").pack(pady=5)

        self.lista_plantas = ctk.CTkComboBox(self, values=[p.nome for p in master.plantas])
        self.lista_plantas.pack(pady=5)

        ctk.CTkButton(self, text="Selecionar", command=self.selecionar_planta).pack(pady=5)
        ctk.CTkButton(self, text="Adicionar planta", command=lambda: master.show_frame(TelaAddPlanta)).pack(pady=5)

    def selecionar_planta(self):
        nome = self.lista_plantas.get()
        if not nome:
            ctk.CTkMessageBox.show_error("Erro", "Selecione uma planta")
            return
        for p in self.master.plantas:
            if p.nome == nome:
                self.master.planta_selecionada = p
                break
        self.master.show_frame(TelaMonitoramento)
        self.master.iniciar_simulacao()

class TelaMonitoramento(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master)

        ctk.CTkLabel(self, text="Monitoramento").pack(pady=10)
        self.lbl_temp = ctk.CTkLabel(self, text="Temperatura: -- °C")
        self.lbl_temp.pack()
        self.lbl_umid = ctk.CTkLabel(self, text="Umidade: -- %")
        self.lbl_umid.pack()

        ctk.CTkButton(self, text="Entrar no modo Tamagotchi", command=master.entrar_tamagotchi).pack(pady=10)
        ctk.CTkButton(self, text="Voltar para seleção de plantas", command=lambda: master.show_frame(TelaPlantas)).pack()

class TelaTamagotchi(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master)

        ctk.CTkLabel(self, text="Modo Tamagotchi").pack(pady=5)
        self.lbl_imagem = ctk.CTkLabel(self)
        self.lbl_imagem.pack(pady=5)

        botoes_frame = ctk.CTkFrame(self)
        botoes_frame.pack(pady=10)

        ctk.CTkButton(botoes_frame, text="Aquecer", command=self.aquecer).grid(row=0, column=0, padx=5)
        ctk.CTkButton(botoes_frame, text="Resfriar", command=self.resfriar).grid(row=0, column=1, padx=5)
        ctk.CTkButton(botoes_frame, text="Umidificar", command=self.umidificar).grid(row=0, column=2, padx=5)
        ctk.CTkButton(botoes_frame, text="Irrigar", command=self.irrigar).grid(row=0, column=3, padx=5)

        ctk.CTkButton(self, text="Voltar", command=master.sair_tamagotchi).pack(pady=10)

        self.img_atual = None
        self.atualizar_imagem("frio.png")

    def atualizar_imagem(self, nome_arquivo):
        caminho = os.path.join(PASTA_PLANTAS_IMG, nome_arquivo)
        if os.path.exists(caminho):
            img = Image.open(caminho).resize((200, 200))
            self.img_atual = ImageTk.PhotoImage(img)
            self.lbl_imagem.configure(image=self.img_atual)
        else:
            self.lbl_imagem.configure(text=f"Imagem {nome_arquivo} não encontrada")

    def aquecer(self):
        # Aquecer: 7 ON, 11 OFF, 9 OFF, 10 OFF
        self.master.enviar_comando_arduino("TEMP_BAIXA ON")
        self.master.enviar_comando_arduino("TEMP_ALTA OFF")
        self.master.enviar_comando_arduino("UMID OFF")
        self.master.enviar_comando_arduino("IRRIGACAO OFF")
        self.atualizar_imagem("frio.png")

    def resfriar(self):
        # Resfriar: 7 OFF, 11 ON, 9 OFF, 10 OFF
        self.master.enviar_comando_arduino("TEMP_BAIXA OFF")
        self.master.enviar_comando_arduino("TEMP_ALTA ON")
        self.master.enviar_comando_arduino("UMID OFF")
        self.master.enviar_comando_arduino("IRRIGACAO OFF")
        self.atualizar_imagem("calor.png")

    def umidificar(self):
        # Umidificar: 7 OFF, 11 OFF, 9 ON, 10 OFF
        self.master.enviar_comando_arduino("TEMP_BAIXA OFF")
        self.master.enviar_comando_arduino("TEMP_ALTA OFF")
        self.master.enviar_comando_arduino("UMID ON")
        self.master.enviar_comando_arduino("IRRIGACAO OFF")
        self.atualizar_imagem("seco.png")

    def irrigar(self):
        # Irrigar: 7 OFF, 11 OFF, 9 OFF, 10 ON
        self.master.enviar_comando_arduino("TEMP_BAIXA OFF")
        self.master.enviar_comando_arduino("TEMP_ALTA OFF")
        self.master.enviar_comando_arduino("UMID OFF")
        self.master.enviar_comando_arduino("IRRIGACAO ON")
        self.atualizar_imagem("arseco.png")

class TelaAddPlanta(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master)

        ctk.CTkLabel(self, text="Adicionar nova planta").pack(pady=5)

        self.ent_nome = ctk.CTkEntry(self, placeholder_text="Nome da planta")
        self.ent_nome.pack(pady=5)

        self.ent_temp_min = ctk.CTkEntry(self, placeholder_text="Temperatura mínima (°C)")
        self.ent_temp_min.pack(pady=5)

        self.ent_temp_max = ctk.CTkEntry(self, placeholder_text="Temperatura máxima (°C)")
        self.ent_temp_max.pack(pady=5)

        self.ent_umid_min = ctk.CTkEntry(self, placeholder_text="Umidade mínima (%)")
        self.ent_umid_min.pack(pady=5)

        self.ent_umid_max = ctk.CTkEntry(self, placeholder_text="Umidade máxima (%)")
        self.ent_umid_max.pack(pady=5)

        self.ent_pais = ctk.CTkEntry(self, placeholder_text="País (opcional, para buscar clima)")
        self.ent_pais.pack(pady=5)

        ctk.CTkButton(self, text="Adicionar", command=self.adicionar).pack(pady=5)
        ctk.CTkButton(self, text="Voltar", command=lambda: master.show_frame(TelaPlantas)).pack(pady=5)

    def adicionar(self):
        nome = self.ent_nome.get().strip()
        try:
            temp_min = float(self.ent_temp_min.get())
            temp_max = float(self.ent_temp_max.get())
            umid_min = float(self.ent_umid_min.get())
            umid_max = float(self.ent_umid_max.get())
        except ValueError:
            ctk.CTkMessageBox.show_error("Erro", "Preencha os valores numéricos corretamente")
            return
        pais = self.ent_pais.get().strip()
        if pais:
            # Buscar clima para confirmar dados (opcional)
            temp_api, umid_api = pegar_clima_por_pais(pais)
            if temp_api is not None:
                # Pode ajustar valores com base no clima, ou só informar
                pass

        if not nome:
            ctk.CTkMessageBox.show_error("Erro", "Nome da planta obrigatório")
            return

        nova_planta = Planta(nome, temp_min, temp_max, umid_min, umid_max, pais if pais else None)
        self.master.plantas.append(nova_planta)
        salvar_plantas(self.master.plantas)
        ctk.CTkMessageBox.show_info("Sucesso", "Planta adicionada!")
        self.master.show_frame(TelaPlantas)

if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")

    app = App()
    app.mainloop()
