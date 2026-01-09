function mostrarSenha() {
    let senha = document.getElementById("senha");
    senha.type = senha.type === "password" ? "text" : "password";
}
