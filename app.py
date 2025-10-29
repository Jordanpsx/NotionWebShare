import os
from dotenv import load_dotenv
# NOVO: Importações para o banco de dados e autenticação
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
# --------------------------------------------------------
from flask import Flask, jsonify, request, render_template, redirect, url_for, flash
import notion_client

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

# Inicializa o Flask
app = Flask(__name__)

# --- NOVO: Configuração do Banco de Dados e Autenticação ---

# 1. Configurações de Segurança e Banco de Dados
app.config['SECRET_KEY'] = 'uma-chave-secreta-muito-dificil-de-adivinhar' # Mude isso para qualquer frase aleatória
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL")

# 2. Inicializa as Extensões
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
# Se um usuário não logado tentar acessar uma página protegida, ele será redirecionado para a rota 'login'
login_manager.login_view = 'login'
login_manager.login_message_category = 'info' # Para estilizar mensagens (opcional)

# --------------------------------------------------------

# --- NOVO: Modelo de Usuário (Nossa tabela no DB) ---

# A classe 'User' herda de 'UserMixin' (para o Flask-Login) e 'db.Model' (para o SQLAlchemy)
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    # A senha terá 60 caracteres, pois é o tamanho do hash do Bcrypt
    password = db.Column(db.String(60), nullable=False)
    # O campo que planejamos para vincular ao Notion!
    notion_tag = db.Column(db.String(100), unique=True, nullable=False)

    def __repr__(self):
        return f"User('{self.email}', '{self.notion_tag}')"

# Esta função é exigida pelo Flask-Login para saber como carregar um usuário a partir do ID da sessão
@login_manager.user_loader
def load_user(user_id):
    # Converte o user_id (que é uma string) para inteiro
    return User.query.get(int(user_id))

# --------------------------------------------------------

# --- Inicialização do Cliente Notion (sem mudanças) ---
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("DATABASE_ID")

try:
    notion = notion_client.Client(auth=NOTION_TOKEN)
    print("Cliente Notion inicializado com sucesso.")
except Exception as e:
    print(f"Erro ao inicializar cliente Notion: {e}")
    notion = None
# --------------------------------------------------------

# --- Nossas Rotas ---

# Rota Principal (Homepage)
@app.route("/")
def index():
    # Agora só mostramos a página de tarefas se o usuário estiver logado
    if current_user.is_authenticated:
        return render_template('index.html')
    else:
        # Se não, mandamos ele para o login
        return redirect(url_for('login'))

# --- NOVO: Rotas de Autenticação (Login, Registro, Logout) ---

@app.route("/login", methods=['GET', 'POST'])
def login():
    # Se o usuário já está logado, manda ele para a home
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Procura o usuário no banco de dados pelo email
        user = User.query.filter_by(email=email).first()
        
        # Se o usuário existir e a senha estiver correta (comparando o hash)
        if user and bcrypt.check_password_hash(user.password, password):
            login_user(user) # "Loga" o usuário na sessão
            flash('Login realizado com sucesso!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Login falhou. Verifique seu email e senha.', 'danger')
            
    return render_template('login.html', title='Login')

# Em app.py, substitua sua rota /register por esta:

@app.route("/register", methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        notion_tag = request.form.get('notion_tag')

        # 1. Verifica se o usuário/tag já existe no NOSSO banco (PostgreSQL)
        user_exists = User.query.filter_by(email=email).first()
        tag_exists = User.query.filter_by(notion_tag=notion_tag).first()

        if user_exists:
            flash('Este email já está cadastrado.', 'danger')
        elif tag_exists:
            flash(f'O nome de usuário "{notion_tag}" já está em uso. Escolha outro.', 'danger')
        else:
            # --- NOVO: LÓGICA DE SINCRONIZAÇÃO COM O NOTION ---
            try:
                # 2. Busca a estrutura atual da base de dados no Notion
                db_info = notion.databases.retrieve(database_id=DATABASE_ID)
                
                # 3. Pega as opções (tags) existentes da propriedade "Responsáveis"
                responsaveis_prop = db_info.get('properties', {}).get('Responsáveis', {})
                existing_options = responsaveis_prop.get('multi_select', {}).get('options', [])
                
                # 4. Cria uma lista apenas com os nomes das tags existentes
                existing_names = [opt['name'] for opt in existing_options]

                # 5. Verifica se a nova tag (ex: "Jordan") JÁ EXISTE no Notion
                if notion_tag not in existing_names:
                    print(f"A tag '{notion_tag}' não existe no Notion. Criando...")
                    
                    # 6. Se não existir, adiciona a nova tag à lista
                    # (Podemos adicionar uma cor aleatória, mas 'name' é o suficiente)
                    existing_options.append({"name": notion_tag})
                    
                    # 7. Envia a atualização para a API do Notion, alterando as propriedades
                    notion.databases.update(
                        database_id=DATABASE_ID,
                        properties={
                            "Responsáveis": { # O nome exato da sua coluna
                                "multi_select": {
                                    "options": existing_options # Envia a lista completa (antigas + nova)
                                }
                            }
                        }
                    )
                    print(f"Tag '{notion_tag}' criada com sucesso no Notion.")
                else:
                    print(f"A tag '{notion_tag}' já existe no Notion. Nenhuma ação necessária.")

            except notion_client.errors.APIResponseError as e:
                print(f"Erro na API do Notion ao tentar criar a tag: {e}")
                flash(f'Erro ao sincronizar com o Notion. Tente novamente.', 'danger')
                # Se der erro no Notion, não continuamos o cadastro
                return render_template('register.html', title='Registrar')
            except Exception as e:
                print(f"Erro inesperado durante a sincronização: {e}")
                flash('Um erro inesperado ocorreu. Tente novamente.', 'danger')
                return render_template('register.html', title='Registrar')
            # --- FIM DA NOVA LÓGICA ---

            # 8. Se tudo deu certo (local e Notion), cria o usuário no NOSSO banco
            hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
            user = User(email=email, password=hashed_password, notion_tag=notion_tag)
            
            db.session.add(user)
            db.session.commit()
            
            flash('Sua conta foi criada! A tag foi sincronizada com o Notion. Você já pode fazer o login.', 'success')
            return redirect(url_for('login'))
            
    return render_template('register.html', title='Registrar')

@app.route("/logout")
def logout():
    logout_user() # "Desloga" o usuário da sessão
    return redirect(url_for('login'))

# --------------------------------------------------------

# --- Nossas Rotas de API (Agora protegidas!) ---

@app.route("/api/tarefas")
@login_required # NOVO: Só permite acesso se o usuário estiver logado
def get_tarefas():
    if not notion:
        return jsonify({"erro": "Cliente Notion não inicializado"}), 500
    
    # --- NOVO: Lógica de Filtragem ---
    # Agora vamos filtrar tarefas baseadas no 'notion_tag' do usuário logado
    user_tag = current_user.notion_tag
    # --------------------------------
    
    try:
        # NOVO: Adicionamos um 'filter' ao nosso query do Notion!
        response = notion.databases.query(
            database_id=DATABASE_ID,
            filter={
                "property": "Responsáveis", # O nome da sua coluna Multi-select
                "multi_select": {
                    "contains": user_tag # Filtra se o multi-select CONTÉM a tag do usuário
                }
            }
        )
        tarefas = response.get("results", [])
        return jsonify({
            "total_tarefas": len(tarefas),
            "tarefas": tarefas
        })
    except notion_client.errors.APIResponseError as e:
        print(f"Erro na API do Notion: {e}")
        return jsonify({"erro": str(e)}), 500
    except Exception as e:
        print(f"Erro inesperado: {e}")
        return jsonify({"erro": str(e)}), 500
    
@app.route("/api/tarefa/atualizar_status", methods=['POST'])
@login_required # NOVO: Protegendo a rota de update também
def atualizar_status():
    # O restante desta função permanece exatamente igual
    # (Adicionaríamos checagens de permissão aqui, mas por enquanto está ok)
    if not notion:
        return jsonify({"erro": "Cliente Notion não inicializado"}), 500
    try:
        data = request.get_json()
        page_id = data.get('page_id')
        new_status = data.get('new_status')

        if not page_id or not new_status:
            return jsonify({"erro": "page_id e new_status são obrigatórios"}), 400

        notion.pages.update(
            page_id=page_id,
            properties={
                "Status": {
                    "select": {
                        "name": new_status
                    }
                }
            }
        )
        return jsonify({"sucesso": True, "mensagem": f"Tarefa {page_id} atualizada para {new_status}"})
    except notion_client.errors.APIResponseError as e:
        print(f"Erro na API do Notion: {e}")
        return jsonify({"erro": str(e)}), 500
    except Exception as e:
        print(f"Erro inesperado: {e}")
        return jsonify({"erro": str(e)}), 500
# --------------------------------------------------------

# Roda o servidor se o script for executado diretamente
if __name__ == "__main__":
    # NOVO: Contexto da aplicação para criar o banco de dados
    with app.app_context():
        # Cria todas as tabelas (ex: a tabela User) que definimos, se elas não existirem
        db.create_all()
        print("Tabelas do banco de dados verificadas/criadas.")
        
    app.run(debug=True)