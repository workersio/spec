use clap::{Parser, Subcommand};

mod config;
mod generate;
mod init;
mod run;
mod save;
mod setup;
mod share;

#[derive(Parser)]
#[command(
    name = "workers-spec",
    about = "Share Claude Code sessions as replayable specs",
    before_help = concat!(
        "\n\n",
        " ███████╗██████╗ ███████╗ ██████╗███████╗\n",
        " ██╔════╝██╔══██╗██╔════╝██╔════╝██╔════╝\n",
        " ███████╗██████╔╝█████╗  ██║     ███████╗\n",
        " ╚════██║██╔═══╝ ██╔══╝  ██║     ╚════██║\n",
        " ███████║██║     ███████╗╚██████╗███████║\n",
        " ╚══════╝╚═╝     ╚══════╝ ╚═════╝╚══════╝\n",
        "                          by workers.io\n",
    )
)]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// View or update server configuration
    Config {
        /// Set the server URL
        #[arg(long)]
        server_url: Option<String>,
        /// Reset to default server
        #[arg(long)]
        reset: bool,
    },
    /// Generate a spec from a Claude Code session and upload it
    Share {
        /// The Claude Code session ID
        session_id: String,
        /// Workspace path for session file lookup
        #[arg(long, short)]
        workspace: Option<String>,
    },
    /// Generate a spec from a Claude Code session and save it locally in .spec/
    Save {
        /// The Claude Code session ID
        session_id: String,
        /// Workspace path for session file lookup
        #[arg(long, short)]
        workspace: Option<String>,
    },
    /// Fetch and display a shared spec
    Run {
        /// Spec URL or ID
        url_or_id: String,
        /// Output full spec content instead of preview
        #[arg(long)]
        full: bool,
    },
    /// Interactive setup wizard
    Init,
    /// Check server health
    Status,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();

    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive(tracing::Level::WARN.into()),
        )
        .init();

    match cli.command {
        Commands::Config { server_url, reset } => {
            init::run(server_url.as_deref(), reset)?;
        }
        Commands::Share {
            session_id,
            workspace,
        } => {
            share::run(&session_id, workspace.as_deref()).await?;
        }
        Commands::Save {
            session_id,
            workspace,
        } => {
            save::run(&session_id, workspace.as_deref()).await?;
        }
        Commands::Run { url_or_id, full } => {
            run::run(&url_or_id, full).await?;
        }
        Commands::Init => {
            setup::run().await?;
        }
        Commands::Status => {
            let cfg = config::Config::load()?;
            println!("Server: {}", cfg.api_url);
            let client = reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(3))
                .build()?;
            match client.get(format!("{}/health", cfg.api_url)).send().await {
                Ok(resp) if resp.status().is_success() => println!("Health: OK"),
                Ok(resp) => println!("Health: server returned {}", resp.status()),
                Err(_) => println!("Health: unreachable"),
            }
        }
    }

    Ok(())
}
