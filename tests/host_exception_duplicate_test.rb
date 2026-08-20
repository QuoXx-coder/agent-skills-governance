#!/usr/bin/env ruby
# frozen_string_literal: true

require "digest"
require "fileutils"
require "json"
require "open3"
require "tmpdir"
require "yaml"

AUDIT = File.expand_path("../scripts/audit-skills", __dir__)

def write_skill(path)
  Dir.mkdir(path)
  File.write(File.join(path, "SKILL.md"), <<~SKILL)
    ---
    name: grill-me
    description: Test skill.
    ---
  SKILL
end

def content_hash(root)
  prefix = File.expand_path(root) + File::SEPARATOR
  rows = Dir.glob(File.join(root, "**", "*"), File::FNM_DOTMATCH)
    .select { |path| File.file?(path) && File.basename(path) != ".DS_Store" }
    .sort_by { |path| File.expand_path(path).delete_prefix(prefix) }
    .map { |path| "#{File.expand_path(path).delete_prefix(prefix)}\0#{Digest::SHA256.file(path).hexdigest}\n" }
  Digest::SHA256.hexdigest(rows.join)
end

def write_fake_codex(bin, marker)
  FileUtils.mkdir_p(bin)
  fake_codex = File.join(bin, "codex")
  File.write(fake_codex, <<~RUBY)
    #!/usr/bin/env ruby
    File.write(ENV.fetch("CODEX_MARKER"), ARGV.join(" "))
  RUBY
  File.chmod(0o755, fake_codex)
end

Dir.mktmpdir("agent-skills-host-exception-test") do |root|
  canonical = File.join(root, "canonical")
  home = File.join(root, "home")
  Dir.mkdir(canonical)
  Dir.mkdir(home)
  public_skill = File.join(canonical, "grill-me")
  workbuddy_skills = File.join(home, ".workbuddy", "skills")
  FileUtils.mkdir_p(workbuddy_skills)
  write_skill(public_skill)
  write_skill(File.join(workbuddy_skills, "grill-me"))

  registry = {
    "skills" => [{
      "name" => "grill-me",
      "scope" => "global",
      "source_path" => public_skill,
      "targets" => ["workbuddy"],
      "host_exceptions" => { "workbuddy" => "uses WorkBuddy Marketplace skill" },
      "content_sha256" => content_hash(public_skill)
    }]
  }
  registry_path = File.join(root, "registry.yaml")
  File.write(registry_path, YAML.dump(registry))
  FileUtils.mkdir_p(File.join(public_skill, ".git"))
  File.write(File.join(public_skill, ".git", "HEAD"), "ref: refs/heads/main\n")

  bin = File.join(root, "bin")
  marker = File.join(root, "codex-invoked")
  write_fake_codex(bin, marker)

  environment = {
    "PATH" => [bin, ENV.fetch("PATH")].join(File::PATH_SEPARATOR),
    "CODEX_MARKER" => marker
  }
  stdout, stderr, status = Open3.capture3(
    environment,
    AUDIT,
    "--format", "json",
    "--home", home,
    "--registry", registry_path,
    "--canonical-root", canonical,
    "--temp-root", File.join(root, "tmp")
  )
  raise "audit failed: #{stderr}" unless status.success?
  raise "default audit must not invoke codex" if File.exist?(marker)

  _stdout, check_stderr, check_status = Open3.capture3(
    environment,
    AUDIT,
    "--format", "json",
    "--home", home,
    "--registry", registry_path,
    "--canonical-root", canonical,
    "--temp-root", File.join(root, "tmp"),
    "--check-codex-config"
  )
  raise "explicit Codex check failed: #{check_stderr}" unless check_status.success?
  raise "explicit Codex check did not invoke codex" unless File.exist?(marker)
  raise "unexpected Codex check arguments" unless File.read(marker) == "app-server --strict-config --stdio"

  issues = JSON.parse(stdout).fetch("issues")
  hash_drift = issues.find { |issue| issue["code"] == "content-hash-drift" }
  raise "Git metadata must not cause a hash drift: #{hash_drift}" if hash_drift

  duplicate = issues.find { |issue| issue["code"] == "duplicate-real-skill" }
  raise "host exception must suppress duplicate-real-skill: #{duplicate}" if duplicate
end

puts "host exception duplicate test passed"
