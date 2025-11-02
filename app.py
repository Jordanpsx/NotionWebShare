import os
from dotenv import load_dotenv
# Importações para o banco de dados e autenticação
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
# Importações principais do Flask
from flask import Flask, jsonify, request, render_template, redirect, url_for, flash
import notion_client

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

# Inicializa o Flask
app = Flask(__name__)

# --- Configuração do Banco de Dados e Autenticação ---

# 1. Configurações de Segurança e Banco de Dados
app.config['SECRET_KEY'] = 'uma-chave-secreta-muito-dificil-de-adivinhar'
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL")

# 2. Inicializa as Extensões
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
# Se um usuário não logado tentar acessar uma página protegida, ele será redirecionado para a rota 'login'
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'  # Para estilizar mensagens (opcional)

# --------------------------------------------------------

# --- Modelo de Usuário (Nossa tabela no DB) ---

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

# --- Rotas Principais (Páginas) ---

# Rota Principal (Homepage)
@app.route("/")
def index():
    # Agora só mostramos a página de tarefas se o usuário estiver logado
    if current_user.is_authenticated:
        return render_template('index.html')
    else:
        # Se não, mandamos ele para o login
        return redirect(url_for('login'))

# --- Rotas de Autenticação (Login, Registro, Logout) ---

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
            login_user(user)  # "Loga" o usuário na sessão
            flash('Login realizado com sucesso!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Login falhou. Verifique seu email e senha.', 'danger')

    return render_template('login.html', title='Login')


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
            flash(
                f'O nome de usuário "{notion_tag}" já está em uso. Escolha outro.', 'danger')
        else:
            # --- LÓGICA DE SINCRONIZAÇÃO COM O NOTION ---
            try:
                # 2. Busca a estrutura atual da base de dados no Notion
                db_info = notion.databases.retrieve(database_id=DATABASE_ID)

                # 3. Pega as opções (tags) existentes da propriedade "Responsáveis"
                responsaveis_prop = db_info.get(
                    'properties', {}).get('Responsáveis', {})
                existing_options = responsaveis_prop.get(
                    'multi_select', {}).get('options', [])

                # 4. Cria uma lista apenas com os nomes das tags existentes
                existing_names = [opt['name'] for opt in existing_options]

                # 5. Verifica se a nova tag (ex: "Jordan") JÁ EXISTE no Notion
                if notion_tag not in existing_names:
                    print(
                        f"A tag '{notion_tag}' não existe no Notion. Criando...")

                    # 6. Se não existir, adiciona a nova tag à lista
                    existing_options.append({"name": notion_tag})

                    # 7. Envia a atualização para a API do Notion, alterando as propriedades
                    notion.databases.update(
                        database_id=DATABASE_ID,
                        properties={
                            "Responsáveis": {  # O nome exato da sua coluna
                                "multi_select": {
                                    # Envia a lista completa (antigas + nova)
                                    "options": existing_options
                                }
                            }
                        }
                    )
                    print(
                        f"Tag '{notion_tag}' criada com sucesso no Notion.")
                else:
                    print(
                        f"A tag '{notion_tag}' já existe no Notion. Nenhuma ação necessária.")

            except notion_client.errors.APIResponseError as e:
                print(
                    f"Erro na API do Notion ao tentar criar a tag: {e}")
                flash(
                    f'Erro ao sincronizar com o Notion. Tente novamente.', 'danger')
                # Se der erro no Notion, não continuamos o cadastro
                return render_template('register.html', title='Registrar')
            except Exception as e:
                print(f"Erro inesperado durante a sincronização: {e}")
                flash('Um erro inesperado ocorreu. Tente novamente.', 'danger')
                return render_template('register.html', title='Registrar')
            # --- FIM DA LÓGICA DE SINCRONIZAÇÃO ---

            # 8. Se tudo deu certo (local e Notion), cria o usuário no NOSSO banco
            hashed_password = bcrypt.generate_password_hash(
                password).decode('utf-8')
            user = User(email=email, password=hashed_password,
                        notion_tag=notion_tag)

            db.session.add(user)
            db.session.commit()

            flash(
                'Sua conta foi criada! A tag foi sincronizada com o Notion. Você já pode fazer o login.', 'success')
            return redirect(url_for('login'))

    return render_template('register.html', title='Registrar')


@app.route("/logout")
def logout():
    logout_user()  # "Desloga" o usuário da sessão
    return redirect(url_for('login'))

# --------------------------------------------------------

# --- Nossas Rotas de API (Agora protegidas!) ---

@app.route("/api/tarefas")
@login_required  # Só permite acesso se o usuário estiver logado
def get_tarefas():
    if not notion:
        return jsonify({"erro": "Cliente Notion não inicializado"}), 500

    # Lógica de Filtragem
    # Filtra tarefas baseadas no 'notion_tag' do usuário logado
    user_tag = current_user.notion_tag

    try:
        # Adicionamos um 'filter' ao nosso query do Notion!
        response = notion.databases.query(
            database_id=DATABASE_ID,
            filter={
                "property": "Responsáveis",  # O nome da sua coluna Multi-select
                "multi_select": {
                    # Filtra se o multi-select CONTÉM a tag do usuário
                    "contains": user_tag
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
        return jsonify({"erro": "Um erro inesperado ocorreu"}), 500


@app.route("/api/tarefa/atualizar_status", methods=['POST'])
@login_required  # Protegendo a rota de update também
def atualizar_status():
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

# --- Rota de API para CRIAR uma nova tarefa ---
@app.route("/api/tarefa/criar", methods=['POST'])
@login_required
def criar_tarefa():
    if not notion:
        return jsonify({"erro": "Cliente Notion não inicializado"}), 500

    try:
        # Pega o nome da tarefa enviado pelo JavaScript
        data = request.get_json()
        nome_tarefa = data.get('nome_tarefa')

        if not nome_tarefa:
            return jsonify({"erro": "O nome da tarefa é obrigatório"}), 400

        # Pega a tag do usuário que está logado
        user_tag = current_user.notion_tag

        # Define as propriedades da nova página (tarefa) no Notion
        novas_propriedades = {
            "Nome da Tarefa": {  # Propriedade 'Title'
                "title": [
                    {"text": {"content": nome_tarefa}}
                ]
            },
            "Status": {  # Propriedade 'Select'
                "select": {
                    "name": "A Fazer"  # Define o status inicial como "A Fazer"
                }
            },
            "Responsáveis": {  # Propriedade 'Multi-select'
                "multi_select": [
                    {"name": user_tag}  # Atribui a tarefa ao usuário logado
                ]
            }
        }
        
        # Chama a API do Notion para CRIAR a página
        notion.pages.create(
            parent={"database_id": DATABASE_ID},
            properties=novas_propriedades
        )
        
        return jsonify({"sucesso": True, "mensagem": "Tarefa criada com sucesso"})

    except notion_client.errors.APIResponseError as e:
        print(f"Erro na API do Notion ao criar tarefa: {e}")
        return jsonify({"erro": str(e)}), 500
    except Exception as e:
        print(f"Erro inesperado ao criar tarefa: {e}")
        return jsonify({"erro": str(e)}), 500


# --- NOVO: Rota de API para LER o conteúdo de uma tarefa ---
@app.route("/api/tarefa/conteudo/<string:page_id>")
@login_required
def get_tarefa_conteudo(page_id):
    if not notion:
        return jsonify({"erro": "Cliente Notion não inicializado"}), 500

    try:
        # 1. Busca os "filhos" (blocos) da página
        response = notion.blocks.children.list(block_id=page_id)
        
        conteudo_html_parts = []
        results = response.get('results', [])

        # 2. Itera sobre cada bloco
        for block in results:
            # 3. Por enquanto, só nos importamos com blocos do tipo "paragraph"
            if block.get('type') == 'paragraph':
                
                texto_do_bloco_parts = []
                # O texto de um parágrafo é um array de "rich_text"
                for rt in block.get('paragraph', {}).get('rich_text', []):
                    texto_do_bloco_parts.append(rt.get('plain_text', ''))
                
                # 4. Junta os textos e envolve em tags <p> para formatação
                full_text = "".join(texto_do_bloco_parts)
                if full_text:
                    # Adiciona quebra de linha (Notion não usa <p> vazio)
                    conteudo_html_parts.append(f"<p>{full_text}</p>")
                else:
                    # Se o parágrafo estiver vazio (Enter), adiciona uma quebra
                    conteudo_html_parts.append("<br>")


        # 5. Junta todos os parágrafos
        html_final = "".join(conteudo_html_parts)
        
        if not html_final.strip(): # Verifica se o HTML está vazio ou só com <br>
            html_final = "<p><i>Esta tarefa não possui instruções (texto) adicionais.</i></p>"
        
        return jsonify({"sucesso": True, "conteudo": html_final})

    except notion_client.errors.APIResponseError as e:
        print(f"Erro na API do Notion ao buscar blocos: {e}")
        return jsonify({"erro": str(e)}), 500
    except Exception as e:
        print(f"Erro inesperado ao buscar blocos: {e}")
        return jsonify({"erro": str(e)}), 500

# --------------------------------------------------------

# Roda o servidor se o script for executado diretamente
# Este bloco DEVE ser a ÚLTIMA COISA no arquivo.
if __name__ == "__main__":
    # Contexto da aplicação para criar o banco de dados
    with app.app_context():
        # Cria todas as tabelas (ex: a tabela User) que definimos, se elas não existirem
        db.create_all()
        print("Tabelas do banco de dados verificadas/criadas.")

    app.run(debug=True)