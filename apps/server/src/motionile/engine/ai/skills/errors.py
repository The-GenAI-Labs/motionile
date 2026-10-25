class NoStyleSkillError(Exception):
    code = "no_style_skill"

    def __init__(self, slug: str) -> None:
        super().__init__(f"the style skill {slug} is not available")
        self.slug = slug
