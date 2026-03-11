// Prevents additional console window on Windows in release.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod bridge;
mod commands;
mod state;

use state::AppState;

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(AppState::new())
        .invoke_handler(tauri::generate_handler![
            commands::agent::solve,
            commands::agent::cancel,
            commands::agent::debug_log,
            commands::config::get_config,
            commands::config::update_config,
            commands::config::list_models,
            commands::config::save_settings,
            commands::config::get_credentials_status,
            commands::session::list_sessions,
            commands::session::open_session,
            commands::session::delete_session,
            commands::session::get_session_history,
            commands::wiki::get_graph_data,
            commands::wiki::read_wiki_file,
        ])
        .run(tauri::generate_context!("tauri.conf.json"))
        .expect("error while running tauri application");
}
