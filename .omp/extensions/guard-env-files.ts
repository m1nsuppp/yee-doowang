import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";

const FILE_ACCESS_TOOLS: Record<string, true> = {
	read: true,
	write: true,
	edit: true,
	ast_edit: true,
	grep: true,
	glob: true,
	find: true,
	bash: true,
	eval: true,
};

function containsProtectedEnvironmentPath(value: string): boolean {
	const normalized = value
		.replaceAll(/%2e/gi, ".")
		.replaceAll(/%2f/gi, "/")
		.replaceAll("\\", "/");

	return normalized
		.split(/[\s"'`<>()[\]{};,|&=]+/)
		.some(token =>
			token.split("/").some(segment => {
				const fileName = segment.split(/[?#:]/, 1)[0].toLowerCase();
				return fileName.startsWith(".env") && !fileName.endsWith(".example");
			}),
		);
}

function containsProtectedPathInInput(input: unknown): boolean {
	if (typeof input === "string") return containsProtectedEnvironmentPath(input);
	if (Array.isArray(input)) return input.some(containsProtectedPathInInput);
	if (input && typeof input === "object") {
		return Object.values(input).some(containsProtectedPathInInput);
	}
	return false;
}

export default function guardEnvFiles(pi: ExtensionAPI): void {
	pi.on("tool_call", event => {
		if (!FILE_ACCESS_TOOLS[event.toolName]) return;
		if (!containsProtectedPathInInput(event.input)) return;

		return {
			block: true,
			reason: "Access to local .env files is blocked by the project OMP extension.",
		};
	});
}
