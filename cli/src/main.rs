mod commands;
mod installer;
mod registry;

use clap::{Parser, Subcommand};

#[derive(Parser)]
#[command(
    name = "spec",
    about = "workers.io — A plugin marketplace for Claude Code",
    before_help = concat!(
        "\n",
        " ███████╗██████╗ ███████╗ ██████╗\n",
        " ██╔════╝██╔══██╗██╔════╝██╔════╝\n",
        " ███████╗██████╔╝█████╗  ██║     \n",
        " ╚════██║██╔═══╝ ██╔══╝  ██║     \n",
        " ███████║██║     ███████╗╚██████╗\n",
        " ╚══════╝╚═╝     ╚══════╝ ╚═════╝\n",
        "                    by workers.io\n",
    )
)]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Browse and install plugins from the workers.io marketplace
    Init,
}

fn main() {
    let cli = Cli::parse();

    match cli.command {
        Commands::Init => commands::init::run(),
    }
}
