include!("src/command_names.rs");

fn main() {
    // Generating app-command permissions makes Tauri check every custom
    // command against the capabilities, instead of allowing all of them.
    let manifest = tauri_build::AppManifest::new().commands(COMMAND_NAMES);
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(manifest))
        .expect("failed to run the Tauri build script");
}
